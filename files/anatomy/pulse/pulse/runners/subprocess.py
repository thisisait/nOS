"""Non-agentic subprocess runner.

Executes a job's ``command`` + ``args`` as a child process with bounded
runtime, captured stdout/stderr tails, and structured result.

Doesn't talk to Wing — caller (daemon.run_job) does that around this call.
Keep this module pure-function-shaped for testability.
"""

from __future__ import annotations

import dataclasses
import os
import subprocess
import time


@dataclasses.dataclass(frozen=True)
class RunResult:
    exit_code: int
    duration_s: float
    stdout_tail: str
    stderr_tail: str
    timed_out: bool


def execute(command: str, args: list[str], *,
            timeout_s: float, env: dict[str, str] | None = None,
            cwd: str | None = None) -> RunResult:
    """Run ``command args...`` capped at ``timeout_s``.

    ``timed_out=True`` means the process was SIGKILL'd after timeout.
    Stdout/stderr are tail-trimmed by the caller (we keep the full
    captured output here; trimming happens at Wing API boundary).
    """
    start = time.monotonic()
    final_env = {**os.environ, **(env or {})}
    try:
        proc = subprocess.run(
            [command, *args],
            capture_output=True,
            timeout=timeout_s,
            text=True,
            check=False,
            env=final_env,
            cwd=cwd,
        )
        duration = time.monotonic() - start
        return RunResult(
            exit_code=proc.returncode,
            duration_s=duration,
            stdout_tail=proc.stdout or "",
            stderr_tail=proc.stderr or "",
            timed_out=False,
        )
    except subprocess.TimeoutExpired as e:
        duration = time.monotonic() - start
        # Best-effort capture of partial output
        out = (e.stdout or "") if isinstance(e.stdout, str) \
            else (e.stdout.decode("utf-8", "replace") if e.stdout else "")
        err = (e.stderr or "") if isinstance(e.stderr, str) \
            else (e.stderr.decode("utf-8", "replace") if e.stderr else "")
        return RunResult(
            exit_code=-9,         # convention: -9 == SIGKILL after timeout
            duration_s=duration,
            stdout_tail=out,
            stderr_tail=err,
            timed_out=True,
        )
    except FileNotFoundError as e:
        duration = time.monotonic() - start
        return RunResult(
            exit_code=127,        # convention: 127 == command not found
            duration_s=duration,
            stdout_tail="",
            stderr_tail=f"command not found: {command!r} ({e})",
            timed_out=False,
        )
