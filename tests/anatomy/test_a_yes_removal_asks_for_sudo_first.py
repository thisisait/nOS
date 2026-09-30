"""A -y removal is refused for lack of sudo BEFORE anything escalates.

2026-09-30: `nos --remove=all -y --leave` died in pazny.mac.homebrew on
"sudo: a password is required". The refusal existed (D4) but lived in
tasks/run-mode.yml, imported under `tasks:`, which Ansible runs after
`roles:`. This gate reads the play: the refusal must sit in pre_tasks, and
nothing in pre_tasks before it may escalate.
"""
from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]


def _pre_tasks() -> list[dict]:
    play = yaml.safe_load((REPO / "main.yml").read_text(encoding="utf-8"))[0]
    assert "roles" in play, "main.yml has no roles: section — re-point this gate"
    return play["pre_tasks"]


def test_the_refusal_runs_before_the_roles() -> None:
    names = [t.get("name", "") for t in _pre_tasks()]
    assert "[Run-mode] Refuse non-interactive removal without a sudo path (D4)" in names
    probe = names.index("[Run-mode] Probe passwordless sudo (non-interactive removal preflight)")
    assert probe < names.index("[Run-mode] Refuse non-interactive removal without a sudo path (D4)")


def test_nothing_before_the_refusal_escalates() -> None:
    for t in _pre_tasks():
        if t.get("name") == "[Run-mode] Refuse non-interactive removal without a sudo path (D4)":
            return
        assert not t.get("become"), f"{t.get('name')} escalates before the sudo refusal"
    raise AssertionError("refusal not found")


def test_the_refusal_accepts_either_sudo_path() -> None:
    t = next(t for t in _pre_tasks() if "(D4)" in t.get("name", ""))
    cond = " ".join(t["ansible.builtin.assert"]["that"])
    assert "nos_sudo_password" in cond and "_nos_sudo_probe.rc" in cond
    assert any("assume_yes" in w for w in t["when"]), "must only fire for -y"


def test_run_mode_no_longer_carries_a_second_copy() -> None:
    assert "(D4)\"" not in (REPO / "tasks/run-mode.yml").read_text(encoding="utf-8").replace("'", '"')
