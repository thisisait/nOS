"""Detect running casks is one brew info, not one per outdated token.

MEASURED 2026-09-14 p=11902: the detect task spent ~55s because it ran
``brew info --cask --json=v2 "$cask"`` once per outdated cask. Homebrew's
info is the expensive call; pgrep is cheap. Batch the argv.

WHAT THIS PINS (YAML only — CI has no brew casks):
1. No per-cask ``brew info`` inside a while/for over the outdated list.
2. One ``brew info --cask --json=v2`` (argv list, not ``"$cask"``).
3. Running is still decided by ``pgrep``, never osascript.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
TASKS = REPO / "roles" / "pazny.mac.homebrew" / "tasks" / "main.yml"


def _walk(nodes):
    for t in nodes or []:
        if not isinstance(t, dict):
            continue
        yield t
        for key in ("block", "rescue", "always"):
            yield from _walk(t.get(key))


def _detect() -> dict:
    for t in _walk(yaml.safe_load(TASKS.read_text(encoding="utf-8"))):
        if t.get("name") == "Detect running cask apps":
            return t
    raise AssertionError(f"no Detect running cask apps task in {TASKS}")


def _body() -> str:
    t = _detect()
    return str(t.get("ansible.builtin.shell") or t.get("shell") or "")


def test_detect_does_not_brew_info_per_cask():
    body = _body()
    assert 'brew info --cask --json=v2 "$cask"' not in body
    # Old loop: while/for over `$cask` then brew info that cask.
    assert not re.search(
        r"(while|for)\b[\s\S]{0,200}\$cask[\s\S]{0,200}brew info --cask --json=v2",
        body,
    ), "brew info must not sit inside a while/for over casks"


def test_detect_calls_brew_info_once():
    body = _body()
    assert "--json=v2" in body
    assert "$cask" not in body
    assert body.count("--json=v2") == 1
    assert "*names" in body


def test_detect_still_uses_pgrep_not_osascript():
    body = _body()
    assert "pgrep" in body
    assert "osascript" not in body.lower()
