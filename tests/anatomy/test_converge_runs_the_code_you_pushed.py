"""A converge from a stale checkout succeeds at running the wrong code.

WHAT THIS COST, 2026-08-05. A day's work was committed in a worktree and pushed
to origin/dev. The operator converged from the main checkout — also on `dev`,
seventeen commits behind, because nothing had pulled. The run took an hour and
finished clean. It registered no new Pulse jobs, installed no CLI fix, moved no
pin, and reported success throughout, because everything did succeed: at
executing the previous week's code.

Nothing in the estate was in a position to notice. The playbook is: comparing
HEAD to its upstream costs one second at the start of a run that costs an hour.

THE PROPERTIES THAT MATTER, and each is a way the check could be present and
useless:

  1. It is IMPORTED FROM pre_tasks, and first. A preflight that runs after the
     Homebrew layer has already spent ten minutes is a preflight in name.
  2. It carries `always`. Without it, `nos --tags face` skips the check and the
     tag-filtered runs — the frequent ones — stay unprotected.
  3. It FAILS. A debug message at minute zero of an hour-long run is read by
     nobody; the failure it predicts is silent and total, so the asymmetry
     justifies a stop with an explicit override rather than a warning.
  4. The override exists and is named, so a deliberately pinned checkout has a
     way through that is not "delete the check".

Verified live against the operator's checkout on the day it was written:
`OK dev origin/dev 17 0` — behind by seventeen, which is exactly the condition
the fail task refuses on.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
MAIN = REPO / "main.yml"
PREFLIGHT = REPO / "tasks/preflight-checkout-current.yml"


def test_the_preflight_exists():
    assert PREFLIGHT.is_file(), (
        "tasks/preflight-checkout-current.yml is gone. Without it a converge "
        "from a stale checkout is indistinguishable from a good one."
    )


def test_it_is_imported_from_pre_tasks_and_goes_first():
    src = MAIN.read_text(encoding="utf-8")
    idx = src.find("tasks/preflight-checkout-current.yml")
    assert idx > 0, "main.yml does not import the checkout preflight at all"

    pre = src.find("pre_tasks:")
    assert pre > 0 and idx > pre, "the preflight is not in pre_tasks"

    # Nothing expensive may precede it. `_platform.yml` is the previous first
    # import; if the preflight has drifted below it the check still works but
    # stops being free, and "free" is the argument for it failing hard.
    platform = src.find("tasks/_platform.yml")
    assert platform > idx, (
        "the checkout preflight no longer runs first in pre_tasks. It is the "
        "cheapest check in the playbook and the only one whose failure is "
        "otherwise invisible — it goes before anything that costs time."
    )


def test_the_import_carries_the_always_tag():
    """Otherwise every `--tags` run skips it, and those are the common ones."""
    src = MAIN.read_text(encoding="utf-8")
    idx = src.find("tasks/preflight-checkout-current.yml")
    window = src[idx : idx + 200]
    assert "always" in window, (
        "the preflight import has no `always` tag, so `nos --tags <anything>` "
        "runs without it. Tag-filtered converges are the frequent case."
    )


def test_every_task_in_the_preflight_is_tagged_always():
    src = PREFLIGHT.read_text(encoding="utf-8")
    names = re.findall(r"^- name: (.+)$", src, re.MULTILINE)
    tags = re.findall(r"^  tags: \[(.+)\]$", src, re.MULTILINE)
    assert len(names) == len(tags), (
        f"{len(names)} task(s) but {len(tags)} tag line(s) — a task without tags "
        f"is skipped under --tags, and a half-tagged preflight is worse than "
        f"none because it looks present"
    )
    for t in tags:
        assert "always" in t, f"a preflight task is tagged [{t}] without `always`"


def test_it_refuses_rather_than_warns():
    src = PREFLIGHT.read_text(encoding="utf-8")
    assert "ansible.builtin.fail" in src, (
        "the preflight no longer fails. A warning at second zero of an "
        "hour-long run is read by nobody, and the outcome it predicts — a green "
        "converge of the wrong code — is silent and total."
    )
    # The refusal must key on the BEHIND count, not on something incidental.
    assert re.search(r"_ckt\[3\].*int\).*>\s*0", src, re.DOTALL), (
        "the fail condition no longer tests the behind-count; it may now refuse "
        "on something else, or never"
    )


def test_the_override_exists_and_is_named_in_the_message():
    src = PREFLIGHT.read_text(encoding="utf-8")
    assert "allow_stale_checkout" in src, "no override — a pinned checkout has no way through"
    msg = src[src.find("ansible.builtin.fail") :]
    assert "allow_stale_checkout" in msg, (
        "the refusal message does not name the override, so the only obvious "
        "way past it is to delete the check"
    )


@pytest.mark.parametrize("state", ["NOGIT", "DETACHED", "NOUPSTREAM"])
def test_it_stays_quiet_where_there_is_no_upstream_to_be_behind(state):
    """A tarball, a CI checkout and a detached HEAD are not drift.

    CI matters concretely: `actions/checkout` leaves a detached HEAD, so a
    preflight that refused on it would fail every integration run.
    """
    src = PREFLIGHT.read_text(encoding="utf-8")
    assert state in src, f"the preflight no longer handles the {state} case"
    fail_block = src[src.find("REFUSE") :]
    assert "_ckt[0] | default('') == 'OK'" in fail_block, (
        "the refusal is no longer gated on a successful comparison, so it can "
        "now fire on a checkout that has no upstream at all"
    )
