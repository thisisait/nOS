"""Anatomy CI gate — claude-CLI agents serialize through a run lock.

Firing several claude-CLI agents concurrently made all participants die
mid-run (only agent_run_start landed, never agent_run_end — 2026-05-27,
memory agent-two-runtime-session-gap). "Run them sequentially" was operator
discipline, unenforced in code. pulse-run-agent.sh is the single chokepoint
every agent (conductor/scout/remediator/upgrade-advisor/upgrade-architect)
goes through, so the mutex lives there. This gate pins it so the
serialization can't be silently removed.
"""

from __future__ import annotations

import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
RUNNER = REPO / "files" / "anatomy" / "scripts" / "pulse-run-agent.sh"


def _body() -> str:
    return RUNNER.read_text()


def test_runner_exists():
    assert RUNNER.is_file(), f"{RUNNER} missing"


def test_atomic_mkdir_lock_acquired():
    """The mutex uses an atomic mkdir lock (macOS has no flock)."""
    body = _body()
    assert "NOS_AGENT_LOCK" in body, "no agent-run lock variable"
    assert 'mkdir "$NOS_AGENT_LOCK"' in body, \
        "lock must be acquired with atomic `mkdir` (no flock on macOS)"


def test_lock_released_on_exit():
    """A trap releases the lock on ANY exit (finish, _die, claude failure)."""
    body = _body()
    assert "trap '_release_agent_lock' EXIT" in body, \
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
