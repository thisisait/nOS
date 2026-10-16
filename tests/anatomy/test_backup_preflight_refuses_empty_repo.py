"""configure_backup or install_backrest with an empty restic_repo is refused in
the preflight, in seconds, not by tasks/backup.yml after ~680 tasks (client host,
2026-10-16); Backrest seeds its repo from restic_repo, so it needs one too.
Runs the real main.yml preflight task through Ansible; the rule lives once.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
NAME = "[Preflight] Refuse a backup without a restic_repo"
needs_ansible = pytest.mark.skipif(importlib.util.find_spec("ansible") is None, reason="runs the task through real Ansible")


def _preflight_task() -> dict | None:
    play = yaml.safe_load((REPO / "main.yml").read_text())[0]
    return next((t for t in play["pre_tasks"] if t.get("name") == NAME), None)


@needs_ansible
@pytest.mark.parametrize("extra, refused", [
    ({"configure_backup": True, "restic_repo": ""}, True),
    ({"configure_backup": True}, True),
    ({"configure_backup": True, "restic_repo": "/Volumes/Backup/restic"}, False),
    ({"configure_backup": False, "restic_repo": ""}, False),
    ({"configure_backup": True, "restic_repo": "", "install_backrest": True}, True),
    ({"install_backrest": True, "restic_repo": ""}, True),
    ({"install_backrest": True, "restic_repo": "/Volumes/Backup/restic"}, False),
])
def test_the_preflight_refuses_backup_without_a_repo(tmp_path, extra, refused):
    task = _preflight_task()
    assert task, f"main.yml pre_tasks has no '{NAME}'"
    play = [{"hosts": "localhost", "connection": "local", "gather_facts": False,
             "vars": {"ansible_python_interpreter": sys.executable, **extra}, "tasks": [task]}]
    (tmp_path / "play.yml").write_text(yaml.safe_dump(play))
    r = subprocess.run([sys.executable, "-m", "ansible.cli.playbook", "-i", "localhost,", str(tmp_path / "play.yml")],
                       capture_output=True, text=True, cwd=tmp_path, timeout=120,
                       env={**os.environ, "ANSIBLE_LOCAL_TEMP": str(tmp_path / ".ansible")})
    assert (r.returncode != 0) is refused, r.stdout[-2000:]
    if refused:
        assert "restic_repo is empty" in r.stdout and "config.yml" in r.stdout


def test_the_rule_lives_in_one_place():
    late = [t.get("name") for t in yaml.safe_load((REPO / "tasks/backup.yml").read_text())
            if "restic_repo is empty" in str((t.get("ansible.builtin.fail") or {}).get("msg"))]
    assert not late, f"tasks/backup.yml re-checks restic_repo; the preflight owns it: {late}"
