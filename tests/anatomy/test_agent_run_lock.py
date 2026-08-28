"""Anatomy CI gate — claude-CLI agents serialize through a run lock.

Firing several claude-CLI agents concurrently made all participants die
mid-run (only agent_run_start landed, never agent_run_end — 2026-05-27,
memory agent-two-runtime-session-gap). "Run them sequentially" was operator
discipline, unenforced in code, so a mutex was written.

THIS GATE'S OWN DOCSTRING WAS WRONG UNTIL 2026-08-06. It said
pulse-run-agent.sh "is the single chokepoint every agent goes through, so the
mutex lives there" — and scan-runner.sh had been spawning claude outside it
since long before, holding an unrelated lock of its own. The gate could not
see that, because it only ever read the file it already knew about: it pinned
the implementation, not the law.

So the two halves are now split by what they can actually prove.
  * HERE: the mutex's mechanics — atomic mkdir, PID liveness, non-destructive
    release. These moved to agent-run-lock.sh, which is the one
    implementation; this file follows them there.
  * test_one_agent_lock_for_every_claude.py: that EVERY claude spawner takes
    it, discovered by reading the scripts rather than from a list, and that
    the lock excludes when two runs actually race.
"""

from __future__ import annotations

import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
RUNNER = REPO / "files" / "anatomy" / "scripts" / "pulse-run-agent.sh"
#: The mutex itself, extracted 2026-08-06 so one law has one implementation.
LOCK = REPO / "files" / "anatomy" / "scripts" / "agent-run-lock.sh"


def _body() -> str:
    return LOCK.read_text()


def test_runner_exists():
    assert RUNNER.is_file(), f"{RUNNER} missing"
    assert LOCK.is_file(), f"{LOCK} missing"


def test_the_runner_still_goes_through_the_mutex():
    """Extracting it must not have quietly detached the original caller."""
    body = RUNNER.read_text()
    assert "agent-run-lock.sh" in body, "pulse-run-agent no longer sources the mutex"
    assert "nos_agent_lock_acquire" in body, "pulse-run-agent no longer acquires it"


def test_atomic_mkdir_lock_acquired():
    """The mutex uses an atomic mkdir lock (macOS has no flock). Since Q12
    the unit acquired is a SLOT under that path; exclusion is proven by
    execution in test_cli_lock_excludes_agentkit_slots.py, not here."""
    body = _body()
    assert "NOS_AGENT_LOCK" in body, "no agent-run lock variable"
    assert 'mkdir "$slot"' in body, \
        "a slot must be acquired with atomic `mkdir` (no flock on macOS)"


def test_lock_released_on_exit():
    """A trap releases the lock on ANY exit (finish, _die, claude failure)."""
    body = _body()
    assert "trap 'nos_agent_lock_release' EXIT" in body, \
        "lock must be released via an EXIT trap"


def test_release_is_not_rm_rf():
    """Release uses rmdir + rm -f owner, never `rm -rf` on the lock path —
    a misset NOS_AGENT_LOCK_DIR must not widen the blast radius."""
    body = _body()
    assert 'rmdir "$NOS_AGENT_LOCK"' in body, "release must rmdir the lock dir"
    assert 'rm -rf "$NOS_AGENT_LOCK"' not in body, \
        "release must not `rm -rf` the lock path (destructive-op safety)"


def test_stale_lock_reclaimed_by_pid_liveness():
    """A lock left by a crashed run is reclaimed via a PID-liveness check."""
    body = _body()
    assert "kill -0" in body, \
        "stale lock must be detected with a `kill -0` liveness probe"


def test_held_lock_exits_nonzero_with_guidance():
    """A live holder blocks the second run with an explicit sequential note."""
    body = _body()
    assert "must run sequentially" in body, \
        "the busy-lock message must state the sequential-run contract"
