"""A Pulse timeout must stop the work, not just the process it holds.

MEASURED 2026-08-31, twice in one night:

    librarian:brief-taxonomy    killed at 900s    session ended at 1103s
    librarian:judge-lint-queue  killed at 600s    session ended at  627s

Both `pulse_runs` rows say rc=-9. Both `agent_sessions` rows say
`outcome_satisfied`. The agents finished their work minutes AFTER the estate
recorded them as killed, because `subprocess.run(timeout=)` SIGKILLs the direct
child only — and every agent job's command is `tools/run-agent.sh`, a bash
wrapper whose real work is a `php run-agent.php` grandchild. The shell died;
the agent carried on.

Two truths from one run is bad enough. The expensive half is the lock: the
agent mutex releases through `trap 'nos_agent_lock_release' EXIT` in
agent-run-lock.sh, and SIGKILL does not run traps. Measured at 07:38 that
morning, `~/.nos/agent-run.lock/slot.1` was still held by PID 51683, dead since
05:38. A leaked slot is exactly what makes the NEXT agent job wait 300s and
exit 2 — the failure diagnosed the day before as a scheduling collision and
fixed by moving two cron times. That fix was correct on its own terms; this is
the generator underneath it, and moving cron times would never have reached it.

WHAT THIS GATE ASSERTS, AND WHY IT SPAWNS REAL PROCESSES. The bug is entirely
about process-group membership, so a mock cannot see it: any stub that records
"kill was called" passes on both the broken and the fixed code. The test starts
a shell that backgrounds a sleeper — the exact shape of run-agent.sh — lets the
timeout fire, and then asks the OPERATING SYSTEM whether the grandchild is
still alive. That question has only ever had one honest answer.

Retro-verified 2026-08-31 by restoring `subprocess.run(..., timeout=)`.
"""

from __future__ import annotations

import importlib.util
import os
import pathlib
import subprocess
import sys
import tempfile
import time

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
RUNNER = REPO / "files/anatomy/pulse/pulse/runners/subprocess.py"


def _runner():
    spec = importlib.util.spec_from_file_location("pulse_subproc_runner", RUNNER)
    mod = importlib.util.module_from_spec(spec)
    # Registered before exec: @dataclass resolves annotations through
    # sys.modules[cls.__module__], which is None for a module that ran without
    # being registered — and the failure names dataclasses, not this line.
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def test_the_timeout_reaches_a_backgrounded_grandchild(tmp_path) -> None:
    mod = _runner()
    pidfile = tmp_path / "grandchild.pid"
    # The shape of tools/run-agent.sh: a wrapper that starts the real work as a
    # separate process and waits on it. `python3` rather than `sleep` so the
    # command passes the runner's own allowlist (which bans shell basenames and
    # requires an absolute path under an allowed prefix).
    script = tmp_path / "wrapper.py"
    script.write_text(
        "import os, subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(300)'])\n"
        f"open({str(pidfile)!r}, 'w').write(str(child.pid))\n"
        "child.wait()\n")

    # The allowlist demands an absolute path under /Users/ or /home/ whose
    # basename looks like a tool. tmp_path on macOS is /var/folders/... , so
    # copy the interpreter invocation into a wrapper the allowlist accepts.
    shim = pathlib.Path(tempfile.mkdtemp(dir=pathlib.Path.home())) / "pulsekilltest.py"
    shim.write_text(script.read_text())
    os.chmod(shim, 0o755)

    result = mod.execute(str(_python()), [str(shim)],
                         timeout_s=3, env={}, cwd=str(tmp_path))

    assert result.timed_out is True and result.exit_code == -9, (
        f"expected a timeout kill, got rc={result.exit_code} "
        f"timed_out={result.timed_out} — the fixture did not outlive its budget")

    # Give the group kill a moment to land, then ask the OS.
    grandchild = int(pidfile.read_text().strip())
    for _ in range(50):
        if not _alive(grandchild):
            break
        time.sleep(0.1)
    still_running = _alive(grandchild)
    if still_running:                      # don't leak a 300s sleeper
        try:
            os.kill(grandchild, 9)
        except ProcessLookupError:
            pass
    assert not still_running, (
        f"the wrapper was killed but its grandchild (pid {grandchild}) is still "
        "running. That is the live defect: the agent keeps working after the "
        "estate has recorded the run as killed, and the lock the wrapper's EXIT "
        "trap would have released stays held.")


def _python() -> pathlib.Path:
    """An interpreter path the runner's allowlist accepts (/opt/homebrew, /usr/local
    or under a home directory). The system /usr/bin/python3 is deliberately NOT
    allowlisted, so a test that used it would be testing the allowlist."""
    import shutil
    for candidate in ("python3",):
        found = shutil.which(candidate)
        if found and any(found.startswith(p)
                         for p in ("/opt/homebrew/", "/usr/local/", "/Users/", "/home/")):
            return pathlib.Path(found)
    pytest.skip("no allowlisted python3 on this host to spawn the fixture with")


def test_the_child_leads_its_own_session() -> None:
    """The behavioural test above needs a real spawn; this one is the cheap
    always-runs half. Without `start_new_session` the child shares the daemon's
    process group, and killing that group would kill PULSE ITSELF — so this is
    not merely how the fix works, it is what stops the fix being catastrophic."""
    src = RUNNER.read_text(encoding="utf-8")
    assert "start_new_session=True" in src, (
        "the child no longer leads its own session, so os.killpg would target "
        "the daemon's own group")
    assert "os.killpg" in src, "the timeout no longer kills the group"
