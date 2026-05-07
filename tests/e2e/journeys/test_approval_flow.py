"""Journey: approval flow — A11 agent_approval_request → operator decision.

Walks the full agentic-loop closure path:
  1. Seed an `agent_approval_request` event via HMAC POST (simulates an
     agent posting a high-blast-radius proposal).
  2. GET /approvals as the test operator — verify the seeded request
     appears in pending queue.
  3. GET /approvals/approve/<actor_action_id> — verify 302 redirect.
  4. Verify the matching `agent_approval_decision` event landed with
     verdict=approve, paired via actor_action_id.
  5. Verify post-decision /approvals no longer shows the request.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone

import pytest

WING_URL = os.environ.get("WING_API_URL", "http://127.0.0.1:9000").rstrip("/")
WING_DB = os.environ.get("WING_DB", "/Users/pazny/wing/app/data/wing.db")
HMAC_SECRET = os.environ.get(
    "WING_EVENTS_HMAC_SECRET",
    os.environ.get("BONE_SECRET", ""),
)
TEST_OPERATOR = "e2e-test-approver"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _hmac_post(payload: dict) -> int:
    body = json.dumps(payload).encode()
    ts = str(int(time.time()))
    sig = hmac.new(HMAC_SECRET.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    req = urllib.request.Request(
        WING_URL + "/api/v1/events",
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Wing-Timestamp": ts,
            "X-Wing-Signature": sig,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def _http_get(path: str, headers: dict | None = None,
              follow: bool = True) -> tuple[int, str, str]:
    req = urllib.request.Request(WING_URL + path, headers=headers or {})
    if not follow:
        class _NR(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **kw): return None
        opener = urllib.request.build_opener(_NR())
    else:
        opener = urllib.request.build_opener()
    try:
        r = opener.open(req, timeout=5)
        return r.status, r.read().decode("utf-8", "replace"), r.headers.get("Location", "")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), e.headers.get("Location", "") if e.headers else ""
    except (urllib.error.URLError, OSError) as e:
        return 0, str(e), ""


def _http_post(path: str, headers: dict | None = None,
               follow: bool = False) -> tuple[int, str, str]:
    """POST helper added for A13.7 — state-changing actions are POST-only.
    Empty body is fine (the action data lives in the URL path)."""
    req = urllib.request.Request(WING_URL + path, headers=headers or {},
                                 method="POST", data=b"")
    if not follow:
        class _NR(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **kw): return None
        opener = urllib.request.build_opener(_NR())
    else:
        opener = urllib.request.build_opener()
    try:
        r = opener.open(req, timeout=5)
        return r.status, r.read().decode("utf-8", "replace"), r.headers.get("Location", "")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), e.headers.get("Location", "") if e.headers else ""
    except (urllib.error.URLError, OSError) as e:
        return 0, str(e), ""


@pytest.fixture(autouse=True)
def _require_wing():
    s, _, _ = _http_get("/api/v1/events?limit=1")
    if s == 0:
        pytest.skip(f"Wing not reachable at {WING_URL}")
    if not HMAC_SECRET:
        pytest.skip("WING_EVENTS_HMAC_SECRET not set; HMAC seed path unavailable")


def test_approval_flow_request_to_decision(journey):
    action_id = f"e2e-approval-{uuid.uuid4().hex[:12]}"
    with journey("approval_flow") as j:

        with j.step("seed_approval_request") as s:
            status = _hmac_post({
                "ts": _now(),
                "type": "agent_approval_request",
                "run_id": f"e2e-approval-test-{action_id}",
                "source": "e2e",
                "actor_id": "e2e-mock-agent",
                "actor_action_id": action_id,
                "acted_at": _now(),
                "task": "E2E test: approve me to verify the loop",
                "result": {
                    "summary": "synthetic approval request from e2e suite",
                },
            })
            assert status == 201, f"seed POST returned {status}"
            s.note = f"seeded action_id={action_id[:16]}"

        with j.step("verify_request_in_pending_queue") as s:
            with sqlite3.connect(WING_DB) as conn:
                row = conn.execute(
                    "SELECT type, actor_action_id FROM events "
                    "WHERE actor_action_id=? AND type='agent_approval_request'",
                    (action_id,),
                ).fetchone()
            assert row is not None, f"seeded request {action_id} not in events table"
            s.note = "request landed in events"

        with j.step("operator_clicks_approve") as s:
            # A13.7 (2026-05-07): /approvals/approve/* is now POST-only +
            # super-admin gated. Send X-Authentik-Groups so the gate accepts
            # us, and use POST so requirePostMethod() passes.
            status, _, loc = _http_post(
                f"/approvals/approve/{action_id}",
                headers={
                    "X-Authentik-Username": TEST_OPERATOR,
                    "X-Authentik-Groups": "nos-providers",
                },
                follow=False,
            )
            assert status in (302, 303), (
                f"approve action expected 302/303, got {status}"
            )
            assert "/approvals" in loc, f"expected redirect to /approvals, got {loc}"
            s.note = f"{status} → {loc}"

        # Decision event lands async via Wing internal HMAC POST; settle
        time.sleep(0.5)

        with j.step("verify_decision_landed_with_verdict_approve") as s:
            with sqlite3.connect(WING_DB) as conn:
                row = conn.execute(
                    "SELECT actor_id, result_json FROM events "
                    "WHERE actor_action_id=? AND type='agent_approval_decision' "
                    "ORDER BY id DESC LIMIT 1",
                    (action_id,),
                ).fetchone()
            assert row is not None, (
                f"decision event missing for action_id={action_id} — "
                f"approve click didn't write through /api/v1/events"
            )
            actor, result_json = row
            assert actor == TEST_OPERATOR, f"actor_id mismatch: {actor} != {TEST_OPERATOR}"
            verdict = json.loads(result_json or "{}").get("verdict")
            assert verdict == "approve", f"verdict mismatch: {verdict}"
            s.note = f"verdict=approve, actor={actor}"
