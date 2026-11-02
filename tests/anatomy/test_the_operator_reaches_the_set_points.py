"""On a nos_system_user host the operator's processes reach the set-points dir at once.

THE SYMPTOM (the Linux mini, 2026-11-02). The converge added the operator to group nos,
but the lingering systemd --user manager (Wing, Pulse) kept its old groups until a reboot.
Wing could not traverse /var/lib/nos (root:nos 0750), so PulseRepository::haltFile() fell
back to ~/.nos/halt, wrote the halt there and answered success, while Pulse read
/var/lib/nos/settings/halt — a halt that held nothing.

THE CHECK. roles/pazny.medulla/tasks/linux.yml grants the operator a user ACL: traverse on
the system home, rwx on settings, and a default ACL so a file the medulla writes there stays
writable for the operator. CEILING: the effect is the halt journey on a Linux host.
"""
from __future__ import annotations

from pathlib import Path

import yaml

TASKS = yaml.safe_load((Path(__file__).resolve().parents[2] / "roles/pazny.medulla/tasks/linux.yml").read_text())


def _acl_items() -> list[dict]:
    block = next(t for t in TASKS if t.get("block"))
    task = next(t for t in block["block"] if "ansible.posix.acl" in t)
    assert task["ansible.posix.acl"]["entity"] == "{{ ansible_facts['user_id'] }}"
    assert task["ansible.posix.acl"]["etype"] == "user"
    return task["loop"]


def test_the_operator_may_traverse_the_system_home():
    assert {"path": "{{ nos_system_home }}", "perms": "x", "default": False} in _acl_items()


def test_the_operator_writes_the_set_points_and_what_lands_there():
    items = _acl_items()
    assert {"path": "{{ nos_system_home }}/settings", "perms": "rwx", "default": False} in items
    assert {"path": "{{ nos_system_home }}/settings", "perms": "rw", "default": True} in items
