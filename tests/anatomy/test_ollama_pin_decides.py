"""The ollama pin decides; a newer keg does not fail the run so we can re-pin.

MEASURED 2026-09-14 p=11902. Install had already been `state: present` since
2026-08-27, so brew-during-this-run was not what moved the keg. Linked was
0.34.0, pin was 0.33.3, cellar still had 0.33.3, no shadowing tap — and the
refuse told the operator to `brew upgrade` then re-pin. Sixth time the
recorder failed for being out of date.

WHAT THIS PINS. Three properties, YAML only (CI has no Homebrew):

1. Install is `present`, not `latest`.
2. When the linked keg is not the pin, a task links the pin keg (Homebrew's
   Keg API on the pin prefix — `brew link ollama` always links newest).
3. The refuse does not tell the operator to bump the record. That advance is
   `tools/brew-pin-status.py` plus a commit.

WHAT IT CANNOT DO. Wet-test a keg switch — next `nos` is the reader. A pin
keg gone from the cellar still refuses; that is restore-the-pin, not re-pin.
"""
from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
TASKS = REPO / "roles" / "pazny.openclaw" / "tasks" / "main.yml"


def tasks() -> list[dict]:
    return [t for t in (yaml.safe_load(TASKS.read_text(encoding="utf-8")) or [])
            if isinstance(t, dict)]


def named(fragment: str) -> dict:
    for t in tasks():
        if fragment in str(t.get("name", "")):
            return t
    raise AssertionError(f"no task whose name contains {fragment!r} in {TASKS}")


def _body(task: dict) -> str:
    return " ".join(
        str(task.get(k, ""))
        for k in (
            "ansible.builtin.shell", "ansible.builtin.command",
            "ansible.builtin.fail", "ansible.builtin.debug",
            "community.general.homebrew", "shell", "command", "fail", "debug",
        )
    )


def test_install_is_present_not_latest():
    hb = named("Install Ollama via Homebrew").get("community.general.homebrew")
    assert isinstance(hb, dict) and hb.get("state") == "present", (
        "ollama install is not `state: present`. `latest` is what adopted a "
        "one-day-old formula unattended (2026-08-27) and what the structural "
        "note on ollama_version said cannot hold."
    )


def test_a_newer_keg_is_switched_to_the_pin_before_the_refuse():
    names = [str(t.get("name", "")) for t in tasks()]
    link_i = next(i for i, n in enumerate(names) if "Link the pin keg" in n)
    refuse_i = next(
        i for i, n in enumerate(names)
        if "Refuse when the INSTALLED keg is not the pin" in n
    )
    assert link_i < refuse_i, (
        "the pin-keg switch must run before the refuse; otherwise a cellar "
        "that still has the pin (p=11902: 0.33.3 sitting next to linked "
        "0.34.0) still fails the run"
    )
    link = tasks()[link_i]
    body = _body(link)
    assert "installed_kegs" in body and "keg.link" in body, (
        "the switch does not link the pin keg via Homebrew's Keg API. "
        "`brew link ollama` always links the newest keg, which is the "
        "thing we are switching away from."
    )
    assert link.get("become") is False, (
        "brew-as-root is refused; the keg switch must be become: false"
    )


def test_the_refuse_does_not_tell_the_operator_to_re_pin():
    msg = str(named("Refuse when the INSTALLED keg is not the pin")
              .get("ansible.builtin.fail", {}).get("msg", ""))
    assert "re-pin" not in msg.lower(), (
        "the refuse still tells the operator to re-pin. That is the recorder "
        "failing for being out of date — p=11902, and every ollama bump before it."
    )
    assert "brew-pin-status.py" in msg, (
        "the leftover refuse (pin keg gone) does not point at the reader that "
        "says when the pin may advance"
    )


def test_the_coherent_mismatch_report_does_not_ask_to_edit_the_record():
    msg = _body(named("Report — brew installed a version the pin does not name"))
    assert "Update default.config.yml" not in msg, (
        "the leftover debug still asks to bump the pin to follow the keg"
    )
    assert "state: latest" not in msg, (
        "the leftover debug still describes install as `state: latest`"
    )
