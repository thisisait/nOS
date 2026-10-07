"""Journey: the emergency halt through the API break-glass (`nos halt`).

Halts and resumes through POST /api/v1/admin/{halt,resume} — the CLI's path,
with the wing-halt bearer — and checks that three readers agree after each
act: the /admin Latte page (HALTED / RUNNING), GET /api/v1/admin/state, and
`nos halt --status`. The agent-class bearer (WING_API_TOKEN, the
ansible-provisioned row) must be refused. Offline gate:
tests/anatomy/test_halt_has_a_break_glass.py.

Needs, beyond the journey env: WING_HALT_TOKEN (wing_halt_token, resolved by
tools/run-journeys.sh from ~/.nos/secrets.yml). Written 2026-10-07; not yet run.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import urllib.error
import urllib.request

import pytest

from .test_halt_resume import ADMIN_HEADERS, RESIDUE_PROBES, _emergency_halted, _http, _undo_halt

REPO = pathlib.Path(__file__).resolve().parents[3]
WING_URL = os.environ.get("WING_API_URL", "http://127.0.0.1:9000").rstrip("/")
HALT = os.environ.get("WING_HALT_TOKEN", "")

needs_halt_token = pytest.mark.skipif(not HALT, reason="WING_HALT_TOKEN unset: not resolved from ~/.nos/secrets.yml")


def _api(method: str, path: str, token: str) -> tuple[int, dict]:
    req = urllib.request.Request(WING_URL + path, method=method, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def _nos(*args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, WING_HALT_TOKEN=HALT, NOS_WING_URL=WING_URL)
    return subprocess.run(["bash", str(REPO / "tools/nos"), *args], env=env, capture_output=True, text=True, timeout=30)


def _three_readers_say(halted: bool) -> str:
    status, page, _ = _http("GET", "/admin", headers=ADMIN_HEADERS)
    assert status == 200, f"/admin answered {status}"
    assert ("HALTED" if halted else "RUNNING") in page, "the Latte page disagrees"
    _, state = _api("GET", "/api/v1/admin/state", HALT)
    assert state.get("halt_active") is halted, f"API state disagrees: {state}"
    cli = _nos("halt", "--status")
    assert cli.returncode == 0 and json.loads(cli.stdout).get("halt_active") is halted, cli.stdout + cli.stderr
    return f"page/api/cli all say halted={halted}"


@needs_halt_token
def test_break_glass_halts_and_resumes(journey):
    with journey("halt_break_glass", residue_probes=RESIDUE_PROBES) as j:
        with j.step("agent_bearer_refused") as s:
            code, body = _api("POST", "/api/v1/admin/halt", os.environ.get("WING_API_TOKEN", ""))
            assert code == 403 and not _emergency_halted(), f"agent-class bearer reached the halt: {code} {body}"
            s.note = "ansible-provisioned refused"

        with j.step("cli_halts") as s:
            r = _nos("halt")
            j.mutates("emergency_halt", "pulse_jobs", _undo_halt)
            assert r.returncode == 0, r.stdout + r.stderr
            assert json.loads(r.stdout).get("actor_id") == "wing-halt", r.stdout
            s.note = _three_readers_say(True)

        with j.step("cli_resumes") as s:
            r = _nos("resume")
            assert r.returncode == 0, r.stdout + r.stderr
            assert not _emergency_halted(), "an emergency halt survived the resume"
            s.note = _three_readers_say(False)
