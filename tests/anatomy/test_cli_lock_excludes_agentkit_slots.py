"""The agent-run lock is N=3 slots, and a claude-CLI run still meets nobody.

Q12 (2026-08-28). The May 2026 crash that motivated the mutex was a claude-CLI
crash; an AgentKit run is in-process PHP and does not share that failure mode.
So the lock became a SLOT DIRECTORY: an AgentKit acquisition takes one of three
slots, a CLI acquisition takes all three and is therefore exactly as exclusive
as it was before. One lock path, not two — two locks cannot compare claims,
which is the defect that put a claude spawn outside the mutex for months.

This gate EXECUTES the real script in a temp NOS_AGENT_LOCK_DIR. It never reads
its text: a slot count asserted by grep is a sentence about concurrency, and
concurrency is only ever proven by running two things at once.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

if sys.platform not in ("darwin", "linux"):  # pragma: no cover
    pytest.skip("bash slot-lock probe is POSIX-only", allow_module_level=True)

REPO = Path(__file__).resolve().parents[2]
HELPER = REPO / "files/anatomy/scripts/agent-run-lock.sh"

PROBE = (
    'set -euo pipefail\n'
    f'source "{HELPER}"\n'
    'nos_agent_lock_acquire "$1" "${2:-0}" "${3:-cli}" || exit 2\n'
    'echo HELD; sleep "${4:-5}"\n'
)


@pytest.fixture()
def lab(tmp_path):
    """A probe script + an env pointing the lock at a throwaway directory."""
    probe = tmp_path / "probe.sh"
    probe.write_text(PROBE, encoding="utf-8")
    env = dict(os.environ, NOS_AGENT_LOCK_DIR=str(tmp_path / "agent-run.lock"))
    started: list[subprocess.Popen] = []

    def hold(label: str, kind: str) -> subprocess.Popen:
        proc = subprocess.Popen(
            ["bash", str(probe), label, "0", kind, "30"],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        started.append(proc)
        assert proc.stdout is not None
        assert proc.stdout.readline().strip() == "HELD", f"{label} never acquired"
        return proc

    def acquire(label: str, kind: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(probe), label, "0", kind, "0"],
            env=env, capture_output=True, text=True, timeout=60,
        )

    lab_ns = type("Lab", (), {})()
    lab_ns.hold, lab_ns.acquire, lab_ns.dir = hold, acquire, tmp_path / "agent-run.lock"
    try:
        yield lab_ns
    finally:
        for proc in started:
            proc.kill()
            proc.wait(timeout=10)


def test_a_cli_run_takes_every_slot_and_meets_nobody(lab):
    """The invariant that survives the widening."""
    lab.hold("scan", "cli")
    for kind in ("agentkit", "cli"):
        refused = lab.acquire("second", kind)
        assert refused.returncode == 2, (
            f"a {kind} run acquired while a claude-CLI run held the lock "
            f"(rc={refused.returncode}) — the CLI acquisition is not exclusive"
        )
        assert "another nOS agent run holds the lock" in refused.stderr


def test_three_agentkit_runs_go_abreast_and_a_fourth_does_not(lab):
    """N=3 is the point; N=4 is not."""
    for n in range(3):
        lab.hold(f"agent{n}", "agentkit")
    assert lab.acquire("agent3", "agentkit").returncode == 2, \
        "a fourth AgentKit run acquired — the slot count does not cap anything"
    assert lab.acquire("scan", "cli").returncode == 2, \
        "a claude-CLI run acquired beside three AgentKit runs"


def test_partial_claims_are_not_parked(lab):
    """A refused CLI acquisition must leave the slots it grabbed on the way.
    Parking them is a deadlock: nobody holds them and nobody can take them."""
    lab.hold("agent0", "agentkit")
    assert lab.acquire("scan", "cli").returncode == 2
    for kind in ("agentkit", "agentkit"):
        proc = lab.hold("later", kind)
        assert proc.poll() is None
    assert lab.acquire("agent3", "agentkit").returncode == 2, \
        "more than three slots were free after a refused CLI acquisition"


def test_a_killed_owner_frees_its_slot(lab):
    """Without per-slot liveness one SIGKILLed agent wedges a slot forever —
    a worse outage than the race the lock prevents."""
    victim = lab.hold("victim", "agentkit")
    victim.kill()
    victim.wait(timeout=10)
    assert any(p.name == "owner" for p in lab.dir.rglob("owner")), \
        "the killed run left no owner file — this test would prove nothing"

    reclaimer = lab.acquire("scan", "cli")
    assert reclaimer.returncode == 0 and "HELD" in reclaimer.stdout, (
        f"a slot held by a dead owner was not reclaimed (rc={reclaimer.returncode}): "
        f"{reclaimer.stderr.strip()[:300]}"
    )
    assert "reclaiming stale agent lock" in reclaimer.stderr, "it reclaimed silently"


def test_the_lock_path_is_still_singular(lab):
    """One path, one law. Slots live UNDER the lock dir the callers name —
    a second lock elsewhere is how a claude spawn escaped the mutex before."""
    lab.hold("agent0", "agentkit")
    slots = sorted(p.name for p in lab.dir.iterdir())
    assert slots == ["slot.1"], f"expected one slot dir under the lock path, found {slots}"
