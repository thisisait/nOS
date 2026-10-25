"""Only the scheduler records a Pulse run: an agent's wing.write cannot forge one.

MEASURED 2026-10-25 (row medulla-scheduler, increment c2): POST /api/v1/pulse_runs and
/pulse_runs/<id>/finish took any wing.write bearer, which every agent holds. A run row is the
scheduler's word that a job ran and how it ended, read by red-status and the inbox reconciler,
and a finish moves next_fire_at: an agent could mark a failing job green or push its next run
away. Now both need pulse.run (the medulla's, once it reports over its nerve) or pulse.write
(the converge's token, which the Python daemon uses today).

The real presenter runs over a scratch wing.db, through the harness of
test_wing_api_verbs_need_the_operator_scope (its own tokens plus two added here). An allowed
call "reached" the repository, which the harness leaves unbuilt, so nothing is written.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("_verbs", REPO / "tests/anatomy/test_wing_api_verbs_need_the_operator_scope.py")
verbs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(verbs)

TOKENS_END = "'bffo' => ['face-bff', 'wing.operator,wing.write']]"
HARNESS = verbs._HARNESS.replace(TOKENS_END, TOKENS_END[:-1] + ", 'pw' => ['ansible-provisioned', 'wing.write,pulse.write'],"
                                 " 'pr' => ['medulla', 'wing.write,pulse.run']]")
WHO = {"agent": "write", "legacy_null_scope": "legacy", "operator_token": "op", "scheduler": "pw", "medulla": "pr"}
CALLS = [("runs", {}, {"run_id": "r1", "job_id": "a:b"}), ("runFinish", {"id": "r1"}, {"exit_code": 0})]


def _run(tmp_path) -> list[dict]:
    assert HARNESS != verbs._HARNESS, "the harness's token list moved; this gate added no scheduler token"
    subprocess.run(["php", str(verbs.WING / "bin/init-db.php"), f"--data-dir={tmp_path}"],
                   capture_output=True, check=True, timeout=60)
    cases = [{"presenter": "Pulse", "action": a, "params": p, "body": b, "token": t}
             for a, p, b in CALLS for t in WHO.values()]
    r = subprocess.run(["php", "-d", "error_reporting=E_ALL", "-r", HARNESS, str(verbs.AUTOLOAD),
                        str(tmp_path / "wing.db"), json.dumps(cases)],
                       capture_output=True, text=True, timeout=120, check=False, cwd=verbs.WING)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(r.stdout)["results"]


@verbs.needs_php
@verbs.needs_vendor
def test_only_the_scheduler_records_a_run(tmp_path):
    results = _run(tmp_path)
    for i, (action, _, _) in enumerate(CALLS):
        row = dict(zip(WHO, results[i * len(WHO):(i + 1) * len(WHO)]))
        for denied in ("agent", "legacy_null_scope", "operator_token"):
            assert row[denied]["code"] == 403 and "pulse.run" in (row[denied]["error"] or ""), f"{action} as {denied}: {row[denied]}"
        for allowed in ("scheduler", "medulla"):
            got = row[allowed]  # createRun wraps the unbuilt repository's Error as its own 500
            reached = got["code"] == "reached" or "before initialization" in (got["error"] or "")
            assert reached, f"{action} as {allowed}: {got}"


def test_the_python_daemon_holds_a_token_that_may():
    """Pulse posts runs with pulse_api_token, which is wing_api_token: minted wing.write,pulse.write."""
    assert 'pulse_api_token: "{{ wing_api_token }}"' in (REPO / "roles/pazny.pulse/defaults/main.yml").read_text()
    assert "--scopes=wing.write,pulse.write" in (REPO / "roles/pazny.wing/tasks/post.yml").read_text()


pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")
