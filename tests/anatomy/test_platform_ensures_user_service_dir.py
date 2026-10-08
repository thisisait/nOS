"""The user-scope service directory exists before any role writes into it.

A fresh macOS user has no ``~/Library/LaunchAgents``; it only appears once
some app writes a login item. 34 files render plists there and none ensured
the directory, so the first install died at pazny.bone's "Render launchd
plist" with "Destination directory … does not exist" (thisisait/nOS#44).

``tasks/_platform.yml`` owns the path as ``nos_systemd_user_dir``; it must
also ensure the directory, once, right after setting it.
"""

from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
PLATFORM = REPO / "tasks/_platform.yml"


def _file_args(task):
    return task.get("ansible.builtin.file") or task.get("file") or {}


def test_platform_ensures_nos_systemd_user_dir_after_setting_it():
    tasks = yaml.safe_load(PLATFORM.read_text(encoding="utf-8")) or []
    set_at = [
        i for i, t in enumerate(tasks)
        if "nos_systemd_user_dir" in (t.get("ansible.builtin.set_fact") or t.get("set_fact") or {})
    ]
    assert set_at, "gate went blind: _platform.yml no longer sets nos_systemd_user_dir"

    ensured_at = [
        i for i, t in enumerate(tasks)
        if _file_args(t).get("state") == "directory"
        and "nos_systemd_user_dir" in str(_file_args(t).get("path", ""))
    ]
    assert ensured_at, (
        "_platform.yml sets nos_systemd_user_dir but never ensures the directory; "
        "a fresh macOS has no ~/Library/LaunchAgents"
    )
    assert min(ensured_at) > max(set_at), "ensure the directory after every platform sets it"
