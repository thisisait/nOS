"""A job handed to the medulla (pulse_medulla_jobs) is one it can fire, or the converge stops.

The Python daemon skips exactly the medulla's set, so a job the medulla then refuses would be
fired by nobody. The medulla refuses a `secret:` env (it does not read secrets.yml) and any
runner but subprocess; roles/pazny.pulse runs this check over the real catalog before it
renders either unit (row medulla-scheduler, e).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CHECK = REPO / "files/anatomy/scripts/pulse-medulla-split.py"
CATALOG = [
    {"plugin_name": "wing-base", "job": {"name": "dispatch", "env": {"WING_API_TOKEN": "secret:wing_api_token"}}},
    {"plugin_name": "loop", "job": {"name": "repo-check", "env": {}}},
    {"plugin_name": "hermes-base", "job": {"name": "agent", "runner": "agent", "env": []}},
]


def _check(ids: str, catalog=None) -> subprocess.CompletedProcess:
    if catalog is None:
        env = {**os.environ, "NOS_PLAYBOOK_DIR": str(REPO)}
        catalog = json.loads(subprocess.run([sys.executable, str(REPO / "files/anatomy/scripts/discover-pulse-catalog.py")],
                                            env=env, capture_output=True, text=True, check=True).stdout)
    return subprocess.run([sys.executable, str(CHECK)], input=json.dumps(catalog), capture_output=True, text=True,
                          env={**os.environ, "PULSE_MEDULLA_JOBS": ids}, timeout=60)


def test_a_secret_job_is_refused_by_name():
    out = _check("loop:repo-check,wing:dispatch", CATALOG)
    assert out.returncode == 1, out
    assert "wing:dispatch" in out.stdout and "WING_API_TOKEN" in out.stdout and "secret:" in out.stdout, out.stdout
    assert "loop:repo-check" not in out.stdout, "a clean job was refused"
    assert "secret:wing_api_token" not in out.stdout, "the message names the key, not the reference"


def test_another_runner_and_an_unknown_id_are_refused():
    out = _check("hermes:agent,nope:typo", CATALOG)
    assert out.returncode == 1
    assert "hermes:agent" in out.stdout and "runner agent" in out.stdout, out.stdout
    assert "nope:typo" in out.stdout and "no such job" in out.stdout, out.stdout


def test_the_empty_set_and_a_clean_job_pass():
    assert _check("", CATALOG).returncode == 0
    assert _check("loop:repo-check", CATALOG).returncode == 0


def test_the_real_catalog_holds_a_job_the_medulla_can_and_one_it_cannot():
    """The ids the operator is offered (loop:repo-check) and refused (wing:dispatch-notifications)."""
    assert _check("loop:repo-check").returncode == 0
    refused = _check("wing:dispatch-notifications")
    assert refused.returncode == 1 and "secret:" in refused.stdout, refused


def test_the_role_runs_the_check_before_it_renders():
    tasks = REPO / "roles/pazny.pulse/tasks"
    main = (tasks / "main.yml").read_text(encoding="utf-8")
    assert "pulse-medulla-split.py" in (tasks / "medulla-pulse.yml").read_text(encoding="utf-8"), (
        "the pulse role no longer checks the medulla's set")
    assert main.index("import_tasks: medulla-pulse.yml") < main.index("[pazny.pulse] Render launchd plist") < main.index(
        "import_tasks: medulla-pulse-up.yml"), "check + stop before the daemon reloads, the medulla's start after"
