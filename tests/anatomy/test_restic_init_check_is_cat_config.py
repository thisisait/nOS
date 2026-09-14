"""S7 — restic 'is the repo initialized' reads config, not every snapshot.

p=54800: `restic snapshots` ~31s. `cat config` is the exists check.
Wrong password is also rc!=0; init must not treat that as uninitialized.
"""
from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
BACKUP = REPO / "tasks" / "backup.yml"


def _tasks():
    return yaml.safe_load(BACKUP.read_text(encoding="utf-8"))


def _named(name: str) -> dict:
    return next(t for t in _tasks() if isinstance(t, dict) and t.get("name") == name)


def _cmd(task: dict) -> str:
    return str(task.get("ansible.builtin.command") or task.get("command") or "")


def _when(task: dict) -> str:
    w = task.get("when")
    if w is None:
        return ""
    if isinstance(w, list):
        return " && ".join(str(x) for x in w)
    return str(w)


def test_restic_init_check_is_cat_config():
    cmd = _cmd(_named("[Backup] Check if restic repo is initialized"))
    assert "cat config" in cmd, f"init check must cat config, not list snapshots: {cmd}"
    assert "snapshots" not in cmd


def test_restic_init_does_not_treat_wrong_password_as_uninitialized():
    fail = _named("[Backup] Fail if restic password does not match an existing repo")
    assert "wrong password" in _when(fail)
    init = _named("[Backup] Initialize restic repo")
    when = _when(init)
    assert "restic_repo_check.rc" in when
    assert "wrong password" in when and "not in" in when, (
        f"init on rc!=0 alone would run after a wrong-password cat config: {when}"
    )
