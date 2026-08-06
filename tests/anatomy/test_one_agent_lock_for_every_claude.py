"""Every claude-CLI spawn goes through ONE mutex — measured, not asserted.

WHAT WAS TRUE UNTIL 2026-08-06. `pulse-run-agent.sh` held an mkdir mutex and
described itself, in a comment, as *"the single chokepoint every agent goes
through"*. `files/vuln-scan/scan-runner.sh` spawned claude at 02:00 and never
touched that lock — it holds `/tmp/nos-vulnscan.lock`, which stops a second
SCAN and knows nothing about agents. Two locks, one invariant, and the only
thing claiming they were the same was the sentence above one of them.

The invariant is not cosmetic: concurrent claude-CLI runs killed every
participant in May 2026 (only `agent_run_start` landed, never
`agent_run_end`), which is why the mutex was written in the first place.

This gate holds two things a comment cannot:

  1. every script that spawns claude acquires the SHARED lock — discovered by
     reading the scripts, not from a list someone remembers to update;
  2. the lock actually excludes, proven by running two of them.

The second matters because the first is satisfiable by a call that does
nothing. A lock is a claim about concurrency, so it is tested concurrently.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HELPER = REPO / "files/anatomy/scripts/agent-run-lock.sh"

#: Where a claude-CLI process is spawned today. Derived below rather than
#: trusted: a new spawner that forgets the lock is exactly the regression.
KNOWN_SPAWNERS = {
    "files/anatomy/scripts/pulse-run-agent.sh",
    "files/vuln-scan/scan-runner.sh",
}

SEARCH_ROOTS = ("files", "tools")
#: `claude` invoked as a command word — with a flag (`claude --print`), with an
#: expanded arg array (`claude "${CLAUDE_ARGS[@]}"`), or bare. NOT the word in
#: prose and not `claude.ai`: the match must start a statement, so a leading
#: `#` or any preceding word excludes it. Both live spawners are found by this
#: pattern, and the set assertion below is what proves it kept finding them.
SPAWN = re.compile(r'^\s*(?:[A-Z_]+=\S+\s+)*claude\s+(?:-|"|\$)', re.M)


def _shell_scripts() -> list[Path]:
    out = []
    for root in SEARCH_ROOTS:
        for path in sorted((REPO / root).rglob("*.sh")):
            if "node_modules" in path.parts:
                continue
            out.append(path)
    return out


def test_every_script_that_spawns_claude_takes_the_shared_lock():
    spawners, unlocked = set(), []
    for path in _shell_scripts():
        text = path.read_text(encoding="utf-8", errors="replace")
        if not SPAWN.search(text):
            continue
        rel = str(path.relative_to(REPO))
        spawners.add(rel)
        if "nos_agent_lock_acquire" not in text:
            unlocked.append(rel)

    assert not unlocked, (
        "these scripts spawn claude outside the agent-run mutex, so two "
        "claude-CLI runs can overlap — the arrangement that crashed every "
        "participant in May 2026:\n  " + "\n  ".join(unlocked)
    )
    # If a new spawner appears, this test should be re-read rather than
    # silently widened: the set above documents what was audited.
    assert spawners == KNOWN_SPAWNERS, (
        f"the set of claude spawners changed — audited {sorted(KNOWN_SPAWNERS)}, "
        f"found {sorted(spawners)}. Confirm the new one's wait/refuse policy is "
        f"right for whether a human is watching it, then update this set."
    )


def test_the_law_has_exactly_one_implementation():
    """Two copies of a mutex is how the estate got two locks in the first
    place. The helper is the implementation; callers may only call it."""
    offenders = []
    for path in _shell_scripts():
        if path == HELPER:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if "agent-run.lock" in text and "nos_agent_lock_acquire" not in text:
            offenders.append(str(path.relative_to(REPO)))
    assert not offenders, (
        "these scripts name the agent-run lock without going through the "
        "helper — a second implementation of the one law:\n  " + "\n  ".join(offenders)
    )


def test_the_lock_actually_excludes(tmp_path):
    """Two acquisitions, one lock. The second must be refused, not queued
    behind a lock that never engaged."""
    probe = tmp_path / "probe.sh"
    probe.write_text(
        f'source "{HELPER}"\n'
        'nos_agent_lock_acquire "$1" "${2:-0}" || exit 2\n'
        'echo HELD; sleep "${3:-1}"\n',
        encoding="utf-8",
    )
    env = dict(os.environ, NOS_AGENT_LOCK_DIR=str(tmp_path / "agent-run.lock"))

    holder = subprocess.Popen(["bash", str(probe), "holder", "0", "5"],
                              env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        # Wait for the holder to actually own it before racing a second one.
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "HELD", "the holder never acquired"

        second = subprocess.run(["bash", str(probe), "second", "0", "1"],
                                env=env, capture_output=True, text=True, timeout=30)
        assert second.returncode == 2, (
            f"a second agent acquired the lock while the first held it "
            f"(rc={second.returncode}) — the mutex does not exclude"
        )
        assert "another nOS agent run holds the lock" in second.stderr
    finally:
        holder.kill()
        holder.wait(timeout=10)


def test_a_dead_owner_does_not_wedge_the_estate(tmp_path):
    """A lock left by a crashed run is debris, not a claim. Without the
    liveness check, one killed agent would stop every later one forever —
    a worse outage than the race it prevents."""
    lock = tmp_path / "agent-run.lock"
    lock.mkdir()
    # PID 0 is never a live process we can signal; simulate a crashed owner.
    (lock / "owner").write_text("999999 dead-agent 2026-01-01T00:00:00Z\n", encoding="utf-8")

    probe = tmp_path / "probe.sh"
    probe.write_text(f'source "{HELPER}"\nnos_agent_lock_acquire reclaimer 0 || exit 2\necho HELD\n',
                     encoding="utf-8")
    proc = subprocess.run(["bash", str(probe)],
                          env=dict(os.environ, NOS_AGENT_LOCK_DIR=str(lock)),
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0 and "HELD" in proc.stdout, (
        f"a stale lock from a dead owner was not reclaimed (rc={proc.returncode}): "
        f"{proc.stderr.strip()[:300]}"
    )
    assert "reclaiming stale agent lock" in proc.stderr, "it reclaimed silently"


def test_refusal_is_not_success():
    """`exit 0` on a refusal is the absence-reads-as-calm shape. Both callers
    must carry the refusal out in the exit code."""
    for rel in sorted(KNOWN_SPAWNERS):
        text = (REPO / rel).read_text(encoding="utf-8")
        block = text[text.find("nos_agent_lock_acquire"):]
        block = block[:400]
        assert re.search(r"exit\s+2", block), (
            f"{rel} does not exit non-zero when the agent lock is refused — a "
            f"run that never happened would read as a quiet night"
        )


if sys.platform not in ("darwin", "linux"):  # pragma: no cover
    pytest.skip("bash mutex probe is POSIX-only", allow_module_level=True)
