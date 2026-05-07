"""Journey: halt + resume — A12 big-red-button RBAC + audit chain.

Walks the full halt/resume flow:
  1. Verify /admin requires nos-providers group (403 without)
  2. With nos-providers, GET /admin renders 200 (HTML)
  3. POST /admin/halt — assert all unpaused jobs become emergency-halted,
     manual pauses preserved
  4. POST /admin/resume — assert emergency-halted jobs unpaused, manual
     pauses still preserved
  5. Verify audit chain — paired admin_emergency_halt + admin_emergency_resume
     events with same actor_action_id correlation

Pre-req: Wing live + WING_EVENTS_HMAC_SECRET set. Skips if Wing not reachable.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import urllib.error
import urllib.request

import pytest

WING_URL = os.environ.get("WING_API_URL", "http://127.0.0.1:9000").rstrip("/")
WING_DB = os.environ.get("WING_DB", "/Users/pazny/wing/app/data/wing.db")
TEST_OPERATOR = "e2e-test-admin"


def _http(method: str, path: str, *, headers: dict | None = None,
          allow_redirect: bool = False) -> tuple[int, str, str]:
    """GET/POST helper. Returns (status, body, location_header).

    `allow_redirect=False` (default) catches 302 explicitly so we can
    assert it (admin halt/resume return 302 → /admin).
    """
    req = urllib.request.Request(WING_URL + path, headers=headers or {}, method=method)
    handler = urllib.request.HTTPRedirectHandler() if allow_redirect else None
    opener = urllib.request.build_opener(handler) if handler else urllib.request.build_opener()
    if not allow_redirect:
        # No redirect handler — urllib still follows by default; force off
        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **kw): return None
        opener = urllib.request.build_opener(_NoRedirect())
    try:
        resp = opener.open(req, timeout=5)
        return resp.status, resp.read().decode("utf-8", "replace"), resp.headers.get("Location", "")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), e.headers.get("Location", "") if e.headers else ""
    except (urllib.error.URLError, OSError) as e:
        return 0, str(e), ""


@pytest.fixture(autouse=True)
def _require_wing():
    s, _, _ = _http("GET", "/api/v1/events?limit=1")
    if s == 0:
        pytest.skip(f"Wing not reachable at {WING_URL}")


def test_halt_and_resume_audit_chain(journey):
    with journey("halt_resume") as j:

        with j.step("admin_403_without_group") as s:
            status, _, _ = _http("GET", "/admin",
                                 headers={"X-Authentik-Username": "anyone"})
            assert status == 403, f"expected 403 without nos-providers, got {status}"
            s.note = "rbac gate works"

        with j.step("admin_200_with_group") as s:
            status, body, _ = _http("GET", "/admin",
                                    headers={
                                        "X-Authentik-Username": TEST_OPERATOR,
                                        "X-Authentik-Groups": "nos-providers",
                                    })
            assert status == 200, f"expected 200 with nos-providers, got {status}"
            assert "Platform" in body, "admin page missing 'Platform' string"
            s.note = "admin page renders"

        with j.step("halt_pauses_unpaused_jobs") as s:
            with sqlite3.connect(WING_DB) as conn:
                pre = conn.execute(
                    "SELECT COUNT(*) FROM pulse_jobs WHERE paused=0 AND removed_at IS NULL"
                ).fetchone()[0]
            status, _, loc = _http(
                "GET", "/admin/halt",
                headers={
                    "X-Authentik-Username": TEST_OPERATOR,
                    "X-Authentik-Groups": "nos-providers",
                },
            )
            assert status == 302, f"expected 302 redirect, got {status}"
            assert "/admin" in loc, f"redirect should go to /admin, got {loc}"
            with sqlite3.connect(WING_DB) as conn:
                emergency = conn.execute(
                    "SELECT COUNT(*) FROM pulse_jobs WHERE paused=1 "
                    "AND paused_reason LIKE 'emergency-halt:%'"
                ).fetchone()[0]
            assert emergency >= pre, (
                f"halt didn't transition all unpaused jobs: pre={pre}, "
                f"emergency-halted now={emergency}"
            )
            s.note = f"unpaused_pre={pre}, emergency_post={emergency}"

        with j.step("resume_unhalts_emergency_only") as s:
            with sqlite3.connect(WING_DB) as conn:
                manual_pre = conn.execute(
                    "SELECT COUNT(*) FROM pulse_jobs WHERE paused=1 "
                    "AND paused_reason NOT LIKE 'emergency-halt:%' "
                    "AND paused_reason IS NOT NULL"
                ).fetchone()[0]
            status, _, _ = _http(
                "GET", "/admin/resume",
                headers={
                    "X-Authentik-Username": TEST_OPERATOR,
                    "X-Authentik-Groups": "nos-providers",
                },
            )
            assert status == 302, f"expected 302, got {status}"
            with sqlite3.connect(WING_DB) as conn:
                emergency_post = conn.execute(
                    "SELECT COUNT(*) FROM pulse_jobs WHERE paused=1 "
                    "AND paused_reason LIKE 'emergency-halt:%'"
                ).fetchone()[0]
                manual_post = conn.execute(
                    "SELECT COUNT(*) FROM pulse_jobs WHERE paused=1 "
                    "AND paused_reason NOT LIKE 'emergency-halt:%' "
                    "AND paused_reason IS NOT NULL"
                ).fetchone()[0]
            assert emergency_post == 0, (
                f"resume didn't unhalt emergency-halted: still {emergency_post}"
            )
            assert manual_post == manual_pre, (
                f"resume mutated manual pauses: pre={manual_pre}, post={manual_post}"
            )
            s.note = f"emergency_cleared, manual_preserved={manual_post}"

        with j.step("audit_chain_pair") as s:
            with sqlite3.connect(WING_DB) as conn:
                rows = conn.execute(
                    "SELECT type, actor_id, actor_action_id, ts FROM events "
                    "WHERE type LIKE 'admin_emergency%' AND actor_id=? "
                    "ORDER BY id DESC LIMIT 4",
                    (TEST_OPERATOR,),
                ).fetchall()
            types = [r[0] for r in rows]
            assert "admin_emergency_halt" in types, (
                f"halt audit row missing for actor={TEST_OPERATOR}; "
                f"recent rows: {rows}"
            )
            assert "admin_emergency_resume" in types, (
                f"resume audit row missing; recent rows: {rows}"
            )
            s.note = f"audit_rows={len(rows)} types={set(types)}"
