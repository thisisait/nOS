"""E2E journey: two end users cannot see each other's agent sessions (face I0).

Drives the face BFF on loopback (FACE_URL, the face_port publish) with the
headers the edge would set: X-Face-Edge-Token (Traefik face-edge) and
X-Authentik-* (the outpost). So the whole chain runs — face hook -> uid ->
face-bff bearer -> Wing — and Wing's own API, read with the operator token,
is the reader that says what was stored. Contract: files/anatomy/contracts/face-wing.yml.

Needs, beyond the journey env: FACE_EDGE_TOKEN (face_edge_token) and, for the
two-user half, E2E_FACE_AGENT — an agent whose agent.yml sets
metadata.end_user: true. None does until I1 opens one; that half skips until then.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
import uuid

import pytest

from ..lib.residue import ResidueProbe
from ..lib.wing_csrf import csrf_post

FACE_URL = os.environ.get("FACE_URL", "http://127.0.0.1:5090").rstrip("/")
WING_URL = os.environ.get("WING_API_URL", "http://127.0.0.1:9000").rstrip("/")
AGENT = os.environ.get("E2E_FACE_AGENT", "")
PREFIX = "nos-tester-e2e-face-"
OPERATOR = {"X-Authentik-Username": "nos-e2e-operator", "X-Authentik-Groups": "nos-providers"}

needs_face = pytest.mark.skipif(
    not os.environ.get("FACE_EDGE_TOKEN"),
    reason="FACE_EDGE_TOKEN unset: face not installed, or not resolved from ~/.nos/secrets.yml")


def _call(url: str, headers: dict, body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    h = {**headers, **({"Content-Type": "application/json"} if data else {})}
    req = urllib.request.Request(url, data=data, headers=h, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, {}


def _user(tag: str) -> dict:
    """Headers for a synthetic tier-3 user. No Authentik account: the edge is simulated."""
    name = f"{PREFIX}{tag}-{uuid.uuid4().hex[:8]}"
    return {"X-Face-Edge-Token": os.environ.get("FACE_EDGE_TOKEN", ""),
            "X-Authentik-Uid": uuid.uuid4().hex, "X-Authentik-Username": name,
            "X-Authentik-Email": f"{name}@e2e.invalid", "X-Authentik-Groups": "nos-users"}


def _face(path: str, user: dict, body: dict | None = None) -> tuple[int, dict]:
    return _call(FACE_URL + path, user, body)


def _wing_rows(agent: str) -> list[dict]:
    """The reader: Wing's own rows, operator bearer, unfiltered. Raises if unreadable."""
    code, body = _call(f"{WING_URL}/api/v1/agents/{agent}/sessions",
                       {"Authorization": f"Bearer {os.environ['WING_API_TOKEN']}"})
    if code != 200:
        raise RuntimeError(f"Wing session list unreadable: HTTP {code}")
    return body.get("data", [])


def _running_test_sessions() -> list[str]:
    if not AGENT:
        return []
    return [r["uuid"] for r in _wing_rows(AGENT)
            if str(r.get("actor_id", "")).startswith("user:" + PREFIX) and r.get("status") == "running"]


RESIDUE_PROBES = (ResidueProbe("running session of an e2e face user", _running_test_sessions),)


def _kill(session_uuid: str) -> None:
    """Interrupt via the operator's own button, once the runner has written its row."""
    for _ in range(20):
        if any(r["uuid"] == session_uuid for r in _wing_rows(AGENT)):
            break
        time.sleep(1)
    status, body, _ = csrf_post(WING_URL, "/agents", f"/agents/kill?uuid={session_uuid}", headers=OPERATOR)
    if status not in (302, 303):
        raise RuntimeError(f"kill {session_uuid}: HTTP {status} {body[:200]}")


@needs_face
def test_a_user_sees_no_session_that_is_not_theirs(journey):
    """Mutates nothing: the refusals and the narrowing, against whatever Wing holds."""
    with journey("face_sessions_isolation/read") as j:
        user = _user("reader")
        with j.step("an agent not open to end users is refused") as s:
            code, _ = _face("/bff/agents/conductor/sessions", user, {"prompt": "e2e"})
            s.note = f"status={code}"
            assert code == 403
        with j.step("the user's list holds none of the estate's sessions") as s:
            code, body = _face("/bff/agents/conductor/sessions", user)
            estate = _wing_rows("conductor")
            s.note = f"user sees {len(body.get('sessions', []))}, estate holds {len(estate)}"
            assert code == 200 and body["sessions"] == []
        if not estate:
            pytest.skip("conductor has no sessions on this estate: no foreign uuid to probe")
        with j.step("someone else's session answers 404") as s:
            code, _ = _face(f"/bff/agent-sessions/{estate[0]['uuid']}", user)
            s.note = f"status={code}"
            assert code == 404


@needs_face
@pytest.mark.skipif(not AGENT, reason="E2E_FACE_AGENT unset: no agent sets metadata.end_user before I1")
def test_two_users_cannot_see_each_others_sessions(journey):
    with journey("face_sessions_isolation/two_users", residue_probes=RESIDUE_PROBES) as j:
        alice, bob = _user("a"), _user("b")
        opened = {}
        with j.step("each user opens one session through the BFF") as s:
            for who, h in (("alice", alice), ("bob", bob)):
                code, body = _face(f"/bff/agents/{AGENT}/sessions", h, {"prompt": "e2e isolation probe; answer ok"})
                assert code == 202, f"{who}: HTTP {code}"
                opened[who] = body["uuid"]
                j.mutates("agent_session", body["uuid"], lambda u=body["uuid"]: _kill(u))
            s.note = json.dumps(opened)
        with j.step("Wing stored each session under its user") as s:
            time.sleep(3)
            actors = {r["uuid"]: r["actor_id"] for r in _wing_rows(AGENT)}
            s.note = json.dumps({u: actors.get(u) for u in opened.values()})
            assert actors.get(opened["alice"]) == "user:" + alice["X-Authentik-Username"]
            assert actors.get(opened["bob"]) == "user:" + bob["X-Authentik-Username"]
        with j.step("each list holds only its own") as s:
            for who, h, other in (("alice", alice, "bob"), ("bob", bob, "alice")):
                _, body = _face(f"/bff/agents/{AGENT}/sessions", h)
                seen = {x["uuid"] for x in body.get("sessions", [])}
                assert opened[who] in seen and opened[other] not in seen, f"{who} sees {seen}"
        with j.step("the other's session answers 404") as s:
            code, _ = _face(f"/bff/agent-sessions/{opened['bob']}", alice)
            s.note = f"status={code}"
            assert code == 404
