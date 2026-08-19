"""Journey: an approval is asked, decided once, and provable afterwards.

REWRITTEN 2026-08-11. This walked A11's `/approvals` surface, which was RETIRED
on 2026-08-08 — `ApprovalsPresenter` is gone, an approval is now a
`kind='approval'` row in `agent_questions`, and `/approvals` survives only as a
permanent redirect to `/inbox`. The journey kept pointing at the old address and
failed with a 301 that the CSRF helper reported as if the POST had returned it;
the real 301 came from the GET one step earlier. Every anatomy gate had been
updated for the retirement. This file was the one thing left behind, and because
CI skips the e2e journeys, nothing said so for three days.

What the journey MEASURES has not changed, so the steps map across:

  1. an agent files an approval question            POST /api/v1/inbox/questions
  2. the operator can see it                        GET  /inbox
  3. the operator decides it                        POST /inbox/answer/<uuid>
  4. the decision is provable afterwards            events: agent_approval_decision
  5. it leaves the open queue                       GET  /api/v1/inbox/questions
  6. a second decision cannot overwrite the first   resolve-once

Step 6 is new and it is the point. The router's retirement note says A11's
decision path "could lose a decision two silent ways: empty-secret early return
+ discarded curl result", and `InboxPresenter::actionAnswer` says it exists not
to repeat that. A successor justified by not losing decisions should be asked,
by a test, whether it loses decisions.
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

from ..lib.residue import ResidueProbe
from ..lib.wing_csrf import csrf_post

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


def _with_edge(headers: dict | None) -> dict:
    """SEC-6: inject Wing's edge token (Traefik's wing-edge middleware header)
    so loopback requests pass the edge gate that runs before RBAC. Without it
    every request 403s regardless of forward-auth groups."""
    out = dict(headers or {})
    edge = os.environ.get("WING_EDGE_TOKEN", "")
    if edge:
        out.setdefault("X-Wing-Edge-Token", edge)
    return out


def _http_get(path: str, headers: dict | None = None,
              follow: bool = True) -> tuple[int, str, str]:
    req = urllib.request.Request(WING_URL + path, headers=_with_edge(headers))
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
    req = urllib.request.Request(WING_URL + path, headers=_with_edge(headers),
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


def _api(path: str, method: str = "GET", payload: dict | None = None) -> tuple[int, dict]:
    """Bearer-authenticated call to Wing's agent API (the path an agent takes)."""
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        WING_URL + path, data=data, method=method,
        headers=_with_edge({
            "Authorization": f"Bearer {os.environ.get('WING_API_TOKEN', '')}",
            "Content-Type": "application/json",
        }),
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode("utf-8", "replace")[:200]}
    except (urllib.error.URLError, OSError) as e:
        return 0, {"error": str(e)}


def _decisions(uuid_: str) -> list[tuple[str, str]]:
    """(actor_id, verdict) for every decision event on this question."""
    with sqlite3.connect(WING_DB) as conn:
        rows = conn.execute(
            "SELECT actor_id, result_json FROM events "
            "WHERE actor_action_id=? AND type='agent_approval_decision' "
            "ORDER BY id ASC",
            (uuid_,),
        ).fetchall()
    return [(a, json.loads(r or "{}").get("verdict")) for a, r in rows]


MOCK_AGENT = "e2e-mock-agent"
CLEANUP_OPERATOR = "e2e-cleanup"
CLEANUP_HEADERS = {
    "X-Authentik-Username": CLEANUP_OPERATOR,
    "X-Authentik-Groups": "nos-providers",
}


def _leaked_ask_notifications() -> list[str]:
    """READER: unread 'Agent asks: e2e-mock-agent' inbox rows.

    This is the probe that would have caught the 2026-08-11..16 leak on run
    #2 instead of leaving 29 permanent HIGH rows for a triage to find: the
    journey filed a question, the repository filed the notification, and no
    run ever took either back.
    """
    with sqlite3.connect(WING_DB) as conn:
        rows = conn.execute(
            "SELECT uuid FROM notifications "
            "WHERE title = ? AND wing_inbox_read_at IS NULL",
            (f"Agent asks: {MOCK_AGENT}",),
        ).fetchall()
    return [r[0] for r in rows]


def _open_mock_questions() -> list[str]:
    """READER: agent_questions rows the mock agent still has open."""
    with sqlite3.connect(WING_DB) as conn:
        rows = conn.execute(
            "SELECT uuid FROM agent_questions "
            "WHERE agent_name = ? AND status = 'open'",
            (MOCK_AGENT,),
        ).fetchall()
    return [r[0] for r in rows]


RESIDUE_PROBES = (
    ResidueProbe("unread 'Agent asks' notification", _leaked_ask_notifications),
    ResidueProbe("open e2e-mock-agent question", _open_mock_questions),
)


def _undo_question(question_uuid: str) -> None:
    """Close the question IF still open — the operator path, resolve-once
    safe. A journey that crashed before step 3 leaves it open; a completed
    one already answered it and this is a no-op."""
    with sqlite3.connect(WING_DB) as conn:
        row = conn.execute(
            "SELECT status FROM agent_questions WHERE uuid = ?",
            (question_uuid,),
        ).fetchone()
    if row is None or row[0] != "open":
        return
    status, body, _ = csrf_post(
        WING_URL, "/inbox", f"/inbox/answer/{question_uuid}",
        headers=CLEANUP_HEADERS, extra_post={"answer": "reject"},
    )
    if status not in (302, 303):
        raise RuntimeError(f"cleanup answer returned {status}: {body[:200]}")


def _undo_ask_notification(question_uuid: str) -> None:
    """Mark the paired inbox row read — the operator path (/inbox/mark-read).

    This runs on SUCCESSFUL journeys too: the 29-row leak came from runs
    that PASSED, because answering a question never marks its ask row read
    (that pairing is bin/reconcile-inbox.php's job on the live estate; a
    journey cleans up after itself rather than waiting for the reconciler).
    """
    with sqlite3.connect(WING_DB) as conn:
        rows = conn.execute(
            "SELECT uuid FROM notifications "
            "WHERE title = ? AND wing_inbox_read_at IS NULL "
            "AND metadata_json LIKE ?",
            (f"Agent asks: {MOCK_AGENT}", f'%"{question_uuid}"%'),
        ).fetchall()
    for (notif_uuid,) in rows:
        status, body, _ = csrf_post(
            WING_URL, "/inbox", f"/inbox/mark-read/{notif_uuid}",
            headers=CLEANUP_HEADERS,
        )
        if status not in (302, 303):
            raise RuntimeError(f"mark-read {notif_uuid} returned {status}: {body[:200]}")


def test_approval_flow_request_to_decision(journey):
    marker = uuid.uuid4().hex[:12]
    with journey("approval_flow", residue_probes=RESIDUE_PROBES) as j:

        with j.step("agent_files_an_approval_question") as s:
            status, payload = _api("/api/v1/inbox/questions", "POST", {
                "agent_name": MOCK_AGENT,
                "prompt": f"E2E {marker}: approve me to verify the loop",
                "kind": "approval",
                "severity": "medium",
                "options": ["approve", "reject"],
            })
            assert status in (200, 201), f"filing the question returned {status}: {payload}"
            question_uuid = (payload.get("data") or payload).get("uuid")
            assert question_uuid, f"no uuid in {payload}"
            # Register the undos NOW, not after the test passes — a crash on
            # the very next line is exactly how orphans are born. Unwind is
            # LIFO, so the notification (created by the question insert) is
            # taken back first, then the question itself.
            j.mutates("agent_question", question_uuid,
                      lambda q=question_uuid: _undo_question(q))
            j.mutates("ask_notification", question_uuid,
                      lambda q=question_uuid: _undo_ask_notification(q))
            s.note = f"uuid={question_uuid[:16]}"

        with j.step("operator_can_see_it") as s:
            status, html, _ = _http_get("/inbox", headers={
                "X-Authentik-Username": TEST_OPERATOR,
                "X-Authentik-Groups": "nos-providers",
            })
            assert status == 200, f"/inbox returned {status}"
            assert marker in html, (
                f"the question filed as {question_uuid} is not on /inbox. An "
                "approval nobody can see is an approval nobody can give."
            )
            s.note = "visible in the queue"

        with j.step("operator_decides_it") as s:
            # POST-only + CSRF-validated, so mint the session on /inbox first.
            status, _, loc = csrf_post(
                WING_URL, "/inbox", f"/inbox/answer/{question_uuid}",
                headers={
                    "X-Authentik-Username": TEST_OPERATOR,
                    "X-Authentik-Groups": "nos-providers",
                },
                extra_post={"answer": "approve"},
            )
            assert status in (302, 303), f"answer expected 302/303, got {status}"
            assert "inbox" in loc.lower(), f"expected a redirect to the inbox, got {loc}"
            s.note = f"{status} -> {loc}"

        with j.step("the_decision_is_provable") as s:
            found = _decisions(question_uuid)
            assert found, (
                f"no agent_approval_decision event for {question_uuid}. The "
                "operator decided and the estate cannot show who or what — "
                "which is the whole reason this queue writes lineage."
            )
            actor, verdict = found[-1]
            assert actor == TEST_OPERATOR, f"actor_id mismatch: {actor}"
            assert verdict == "approve", f"verdict mismatch: {verdict}"
            s.note = f"verdict=approve by {actor}"

        with j.step("it_leaves_the_open_queue") as s:
            status, payload = _api("/api/v1/inbox/questions")
            assert status == 200, f"listing open questions returned {status}"
            still_open = [
                q for q in (payload.get("data") or {}).get("questions", [])
                if q.get("uuid") == question_uuid
            ]
            assert not still_open, (
                "the answered question is still listed as open — an operator "
                "would be asked to decide it a second time."
            )
            s.note = "closed"

        with j.step("a_second_decision_cannot_overwrite_the_first") as s:
            # The named reason A11 was retired. Answering again must be refused
            # as already-decided: same stored answer, same author, and NO second
            # decision event — a lineage that records two verdicts for one
            # question cannot say which one held.
            before = len(_decisions(question_uuid))
            status, _, _ = csrf_post(
                WING_URL, "/inbox", f"/inbox/answer/{question_uuid}",
                headers={
                    "X-Authentik-Username": "e2e-second-operator",
                    "X-Authentik-Groups": "nos-providers",
                },
                extra_post={"answer": "reject"},
            )
            assert status in (302, 303), f"second answer expected a redirect, got {status}"

            after = _decisions(question_uuid)
            assert len(after) == before, (
                f"answering twice wrote {len(after) - before} extra decision "
                f"event(s): {after}. Resolve-once is what makes the answer "
                "authoritative; without it the last writer wins silently."
            )
            with sqlite3.connect(WING_DB) as conn:
                stored = conn.execute(
                    "SELECT answer, answered_by FROM agent_questions WHERE uuid=?",
                    (question_uuid,),
                ).fetchone()
            assert stored == ("approve", TEST_OPERATOR), (
                f"the second answer overwrote the first: {stored}"
            )
            s.note = "refused; first decision stands"
