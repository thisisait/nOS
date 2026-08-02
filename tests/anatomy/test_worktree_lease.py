"""The lease that stops a long agent run being cut from under itself.

Fee: docs/hidden_fees/14-a-long-run-cut-from-under.md

Three branches, and the one that matters is HELD — a lease helper that only ever
returns "safe" is a lease helper nobody would notice was broken. Each branch is
exercised against a real process, not a mocked one, because the whole primitive
rests on `kill(0)` telling the truth about liveness.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
TOOL = REPO / "tools" / "worktree-lease.py"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(TOOL), *args],
        cwd=str(REPO), capture_output=True, text=True,
    )


@pytest.fixture(autouse=True)
def _no_stale_lease():
    """The suite must not inherit or leave a lease — it would leak into a real run."""
    _run("release")
    yield
    _run("release")


def test_the_tool_exists_and_is_executable():
    assert TOOL.is_file(), "tools/worktree-lease.py is missing — fee 14 lost its primitive"
    assert os.access(TOOL, os.X_OK), "worktree-lease.py is not executable"


def test_unleased_tree_is_safe_to_reshape():
    r = _run("check")
    assert r.returncode == 0, f"an unleased tree must be safe:\n{r.stdout}{r.stderr}"


def test_a_live_holder_refuses_both_reshape_and_a_second_lease():
    """The branch that earns the file. Held against a REAL live process."""
    holder = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        acq = _run("acquire", "--kind", "workflow", "--label", "test-holder",
                   "--pid", str(holder.pid))
        assert acq.returncode == 0, f"acquire failed:\n{acq.stdout}{acq.stderr}"

        chk = _run("check")
        assert chk.returncode == 3, (
            "check must REFUSE while a live holder leases the tree — this is the "
            f"branch the fee exists for. got {chk.returncode}:\n{chk.stdout}{chk.stderr}"
        )
        # The message must teach the asymmetry, or the rule does not survive
        # contact with whoever hits it at 2am.
        assert "ADDING a path is fine" in chk.stderr
        assert "MOVING or DELETING" in chk.stderr

        second = _run("acquire", "--kind", "session", "--label", "intruder")
        assert second.returncode == 2, (
            f"a second acquire must be refused, got {second.returncode}"
        )
        assert "test-holder" in second.stderr, "the refusal must name the holder"
    finally:
        holder.kill()
        holder.wait()


def test_a_dead_holder_does_not_wedge_the_tree_forever():
    """Liveness is OBSERVED, not self-reported (fee 07's rule applied to a lock).

    A holder that crashed leaves its lease behind. If that lease were believed,
    one crash would make the worktree permanently unreshapeable — a lock whose
    failure mode is worse than the problem it solves.
    """
    holder = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    acq = _run("acquire", "--kind", "workflow", "--label", "doomed", "--pid", str(holder.pid))
    assert acq.returncode == 0
    holder.kill()
    holder.wait()

    for _ in range(20):
        chk = _run("check")
        if chk.returncode == 0:
            break
        time.sleep(0.1)
    assert chk.returncode == 0, (
        f"a dead holder must not wedge the tree:\n{chk.stdout}{chk.stderr}"
    )
    assert "dead" in (chk.stdout + chk.stderr).lower()


def test_status_reports_the_holder_as_data():
    holder = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        _run("acquire", "--kind", "workflow", "--label", "statuscheck", "--pid", str(holder.pid))
        st = json.loads(_run("status").stdout)
        assert st["leased"] is True
        assert st["holder"]["label"] == "statuscheck"
        assert st["holder"]["kind"] == "workflow"
        assert st["dead_because"] is None
    finally:
        holder.kill()
        holder.wait()


def test_the_lease_lives_outside_the_tree_it_guards():
    """A lease file inside the worktree would be a path the lease forbids moving.

    It is also repo state pretending to be runtime state, which is how a
    side-car ends up committed.
    """
    src = TOOL.read_text()
    assert "~/.nos/worktree-leases" in src, "the lease must live in the ~/.nos side-car"
    holder = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        _run("acquire", "--kind", "workflow", "--label", "outside", "--pid", str(holder.pid))
        stray = [p for p in REPO.rglob("*.lease") if ".git" not in str(p)]
        assert not stray, f"lease artefacts inside the worktree: {stray}"
    finally:
        holder.kill()
        holder.wait()
