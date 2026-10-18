"""Anatomy CI gate — a converge over SSH refuses a locked login keychain up front.

MEASURED 2026-10-10, second Mac over SSH: ok=702 failed=1 after ~50 min.
`docker compose build` of face and keap could not load node:22 metadata: the
Docker credential helper reads the login keychain, which an SSH session cannot
unlock ("the current session does not allow user interaction").

Pinned: main.yml probes the keychain on macOS when SSH_CONNECTION is set,
refuses before any stack comes up, prints the unlock command, and is tagged
`always` like the compose up it guards.
"""

from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
MAIN = REPO / "main.yml"


def _main_tasks() -> list[dict]:
    out = []
    for play in yaml.safe_load(MAIN.read_text(encoding="utf-8")):
        for key in ("pre_tasks", "tasks", "post_tasks"):
            out.extend(play.get(key) or [])
    return out


def _mod(t: dict, name: str):
    return t.get(name, t.get(f"ansible.builtin.{name}"))


def _index(pred) -> int:
    return next((i for i, t in enumerate(_main_tasks()) if pred(t)), -1)


def _is_probe(t: dict) -> bool:
    return "show-keychain-info" in str(_mod(t, "command") or _mod(t, "shell") or "")


def _is_refusal(t: dict) -> bool:
    return bool(_mod(t, "fail")) and "unlock-keychain" in str(_mod(t, "fail"))


def test_the_keychain_is_probed_only_over_ssh_on_macos():
    i = _index(_is_probe)
    assert i >= 0, (
        "main.yml no longer probes the login keychain; an SSH converge dies "
        "~50 min in on the Docker credential helper (measured 2026-10-10)")
    when = str(_main_tasks()[i].get("when", ""))
    assert "SSH_CONNECTION" in when and "Darwin" in when, (
        "the probe must be scoped to macOS over SSH; a GUI session unlocks the "
        "keychain itself with a dialog")


def test_the_refusal_prints_the_unlock_command_before_any_stack():
    tasks = _main_tasks()
    r = _index(_is_refusal)
    assert r >= 0, "main.yml has no refusal that prints `security unlock-keychain`"
    core = _index(lambda t: "core-up.yml" in str(t.get("import_tasks", "")))
    assert 0 <= r < core, "the keychain refusal must run before core-up"
    assert _index(_is_probe) < r, "the refusal must follow the probe it reads"
    # Was: tags equal to the no-Docker refusal's. Those tags skip under
    # `--tags pulse` while stack-up's compose up is `always` (2026-10-18).
    # Full reach: test_the_keychain_refusal_precedes_every_compose_up.py.
    assert "always" in (tasks[r].get("tags") or []), (
        "the keychain refusal must run on every --tags run that can build")
