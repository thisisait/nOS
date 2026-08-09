"""A failure message's diagnostic branch must be able to fire.

WHAT HAPPENED, 2026-08-09. The ollama version preflight refuses a converge when
the landed binary disagrees with `ollama_version`, and it has a branch whose
whole job is to name the CAUSE: a third-party tap outranking homebrew/core, so
`brew upgrade ollama` is a no-op. It fired on the operator's converge and the
diagnosis did not appear. They got the generic advice instead — the advice that
does nothing under a shadowing tap.

The probe was:

    brew info ollama 2>&1 | grep -o 'shadows homebrew/core/ollama'

and brew actually prints, backticks and all:

    Warning: `ollama` shadows `homebrew/core/ollama`.

So the pattern never matched, `_ollama_shadow.stdout` was empty, and the `if`
fell through to `else`. Both halves were written in the same commit; neither was
ever rendered against real output, only reasoned about.

THE CLASS, WHICH IS THE ESTATE'S OLDEST. Something that describes a condition is
not something that detects it. A branch nobody has seen fire is a branch that
does not fire — the same argument as the retro-red rule for gates, applied to
diagnostics.

WHAT THIS PINS. The probe emits a COUNT and the condition compares a number.
That is not a style preference: a substring test couples the message to the
exact punctuation of a third party's output, which is what broke. `grep -c`
answers a question whose shape we own.

WHAT IT CANNOT DO. Run `brew` — CI has no Homebrew, and a gate that shells out
to a package manager tests the runner. Reachability against real output stays a
human step, done here by rendering all three arms through Jinja against the
live `grep -c` result before shipping.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
TASKS = REPO / "roles/pazny.openclaw/tasks/main.yml"


def tasks() -> list[dict]:
    return [t for t in (yaml.safe_load(TASKS.read_text(encoding="utf-8")) or [])
            if isinstance(t, dict)]


def named(fragment: str) -> dict:
    for t in tasks():
        if fragment in str(t.get("name", "")):
            return t
    raise AssertionError(f"no task whose name contains {fragment!r} in {TASKS}")


def test_the_shadow_probe_counts_rather_than_matching_prose():
    cmd = str(named("Find any tap shadowing").get("ansible.builtin.shell", ""))
    assert "grep -c" in cmd, (
        "the shadow probe does not count — it matches text. The previous version "
        "matched the literal `shadows homebrew/core/ollama` and brew prints "
        "backticks around both names, so it never fired and the operator got "
        "advice that is a no-op under a shadowing tap.")
    assert "homebrew/core/ollama'" not in cmd, (
        "the probe still pins the full punctuated phrase; match the word")


def test_the_diagnosis_reads_the_probe_as_a_number():
    msg = str(named("Refuse on ollama version mismatch")
              .get("ansible.builtin.fail", {}).get("msg", ""))
    assert "_ollama_shadow.stdout" in msg, "the message never consults the probe"
    assert re.search(r"_ollama_shadow\.stdout[^%]*\|\s*int", msg), (
        "the message tests the probe's output as text. It is a count now, and a "
        "substring test is what coupled this to brew's punctuation.")


def test_an_inconclusive_probe_does_not_read_as_no_shadow():
    """Absence of evidence rendered as evidence of absence is the whole disease."""
    msg = str(named("Refuse on ollama version mismatch")
              .get("ansible.builtin.fail", {}).get("msg", ""))
    assert "_ollama_shadow.rc" in msg, (
        "the message has two arms — shadow and no-shadow — and nothing for 'the "
        "probe did not run'. A skipped or failed probe would then render as a "
        "confident 'no shadowing tap found', sending the operator to `brew "
        "upgrade`, which under a shadow does nothing and looks like it worked.")


def test_the_pin_is_read_back_at_all():
    """The preflight is the only thing that makes ollama_version more than a wish."""
    names = [str(t.get("name", "")) for t in tasks()]
    assert any("Read the landed ollama version" in n for n in names), (
        "nothing reads `ollama --version` back; a declared pin nobody verifies "
        "is how this estate sat two minor versions behind for weeks while every "
        "run reported success")
