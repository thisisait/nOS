"""ansible.cfg must not default-become or auto-discover Homebrew 3.14.

converge-become: ``become = True`` plus ``interpreter_python = auto`` made
brew-as-root the default and, after escalation, rediscovered Homebrew 3.14
(the class that broke ansible-core filter-plugin imports).

WHAT THIS PINS (parse only, no sudo):
1. cfg ``become`` absent or not True — and not replaced by play-level become.
2. cfg ``interpreter_python`` is not auto/auto_silent/auto_legacy.
3. Play interpreter is ``ansible_playbook_python``; inventory does not pin
   ``/opt/homebrew/bin/python3``.
4. A fixture of the 2026-09 cfg fails the same parser (retro-red).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CFG = REPO / "ansible.cfg"
MAIN = REPO / "main.yml"
INVENTORY = REPO / "inventory"

#: The cfg this gate was written against. A stub that only checks the live
#: file can be satisfied by deleting the keys; this string must stay red.
TODAY_CFG = """\
[defaults]
nocows = True
roles_path = ./roles:/etc/ansible/roles
inventory = inventory
become = True
display_skipped_hosts = false
callback_result_format = yaml
interpreter_python = auto
deprecation_warnings = False
"""


def _defaults(text: str) -> dict[str, str]:
    in_defaults = False
    out: dict[str, str] = {}
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            in_defaults = s.lower() == "[defaults]"
            continue
        if not in_defaults or not s or s.startswith(("#", ";")):
            continue
        if "=" not in s:
            continue
        k, _, v = s.partition("=")
        out[k.strip().lower()] = v.strip()
    return out


def cfg_ok(text: str) -> bool:
    d = _defaults(text)
    if d.get("become", "").lower() in ("true", "yes", "1"):
        return False
    interp = d.get("interpreter_python", "")
    if interp.startswith("auto"):
        return False
    return True


def test_todays_cfg_fixture_is_rejected():
    assert not cfg_ok(TODAY_CFG), (
        "the 2026-09 fixture (become True + interpreter auto) must fail this "
        "parser — a stub that always-ok would pin nothing"
    )


def test_live_cfg_is_not_auto_become():
    text = CFG.read_text(encoding="utf-8")
    assert cfg_ok(text), (
        "ansible.cfg still defaults become True or interpreter_python auto* "
        "(converge-become)"
    )


def test_play_does_not_restore_global_become():
    head = "\n".join(MAIN.read_text(encoding="utf-8").splitlines()[:90])
    assert not re.search(r"^  become:\s*(true|yes|True)\s*$", head, re.M), (
        "play-level become: true is the global default under another name"
    )
    assert 'ansible_become_password: "{{ nos_sudo_password }}"' in head


def test_play_interpreter_is_playbook_python_not_homebrew():
    text = MAIN.read_text(encoding="utf-8")
    assert 'ansible_python_interpreter: "{{ ansible_playbook_python }}"' in text, (
        "play vars must pin ansible_playbook_python so become cannot rediscover "
        "Homebrew 3.14"
    )
    inv = INVENTORY.read_text(encoding="utf-8")
    assert "/opt/homebrew/bin/python3" not in inv, (
        "inventory still pins Homebrew python3 (the 3.14 trap)"
    )
    assert "ansible_playbook_python" in text
