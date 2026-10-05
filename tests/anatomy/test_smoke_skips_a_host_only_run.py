"""Gate: a run that brought up no Docker stack does not judge the web smoke.

macOS-15 Integration 2026-10-05: the lane runs host-only by design
(nos_allow_no_docker), every probe was UNREACH, smoke failed the run 0/6.
Runs tasks/post-smoke.yml through real Ansible from a temp dir, where
tools/nos-smoke.py does not exist — so a smoke that runs at all fails.
"""
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(not shutil.which("ansible-playbook"), reason="runs through real Ansible")
@pytest.mark.parametrize("ready,ok", [(False, True), (True, False)])
def test_smoke_runs_only_when_the_stacks_ran(tmp_path, ready, ok):
    play = [{"hosts": "localhost", "gather_facts": False, "connection": "local",
             "vars": {"nos_docker_ready": ready, "ansible_facts": {"env": {"HOME": str(tmp_path)}}},
             "tasks": [{"ansible.builtin.import_tasks": str(REPO / "tasks/post-smoke.yml")}]}]
    (tmp_path / "play.yml").write_text(yaml.safe_dump(play))
    r = subprocess.run(["ansible-playbook", "-i", "localhost,", str(tmp_path / "play.yml")],
                       capture_output=True, text=True, cwd=tmp_path)
    assert (r.returncode == 0) is ok, r.stdout[-1200:]
    if not ready:
        assert "nothing probed" in r.stdout
