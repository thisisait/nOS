"""Non-agentic subprocess runner.

Executes a job's ``command`` + ``args`` as a child process with bounded
runtime, captured stdout/stderr tails, and structured result.

Doesn't talk to Wing — caller (daemon.run_job) does that around this call.
Keep this module pure-function-shaped for testability.
"""

from __future__ import annotations

import dataclasses
import os
import re
import subprocess
import time


# ── SEC H-PULSE1 (2026-05-24): execution-boundary command allowlist ──────────
# Ports PulsePresenter::validatePulseCommand into the runner that actually
# spawns the process, so the allowlist holds regardless of who wrote the
# pulse_jobs row (direct SQLite, agents, a future create-path) — not just the
# one PHP create endpoint. Keep in lockstep with the PHP constants.
_ALLOWED_PREFIXES = ("/opt/homebrew/bin/", "/usr/local/bin/", "/Users/")
_BANNED_BASENAMES = frozenset(
    ("sh", "bash", "zsh", "dash", "csh", "ksh", "fish", "sudo", "su", "env"))
_BASENAME_RE = re.compile(r"^[a-z][a-zA-Z0-9._-]{0,63}$")
_ARG_RE = re.compile(r"^[a-zA-Z0-9._@/:=,+~-]{0,512}$")

# ── SEC M-PULSE2: child-env scoping ──────────────────────────────────────────
# Strip secrets from the inherited env (a job must not be able to read/exfil
# WING_API_TOKEN, ANTHROPIC_API_KEY, *_SECRET, …) and refuse job-supplied
# loader/PATH overrides (DYLD_*/LD_*/PYTHONPATH → allowlisted-binary hijack).
_SECRET_KEY_RE = re.compile(
    r"(SECRET|TOKEN|PASSWORD|CREDENTIAL|ANTHROPIC|HMAC|_KEY$|API_KEY)", re.I)
_BANNED_ENV_RE = re.compile(r"^(DYLD_|LD_|PYTHONPATH$|PATH$|IFS$|BASH_ENV$|ENV$)")


class CommandRejected(ValueError):
    """Raised when a job command/args fail the execution-boundary allowlist."""


def validate_command(command: str, args: list[str]) -> None:
    """Mirror of PulsePresenter::validatePulseCommand. Raises CommandRejected."""
    if not command or command[0] != "/":
        raise CommandRejected("command must be an absolute path")
    if not any(command.startswith(p) for p in _ALLOWED_PREFIXES):
        raise CommandRejected("command path not in Pulse allowlist")
    basename = os.path.basename(command)
    if basename in _BANNED_BASENAMES:
        raise CommandRejected(f"command basename {basename!r} is banned (shell interpreter)")
    if not _BASENAME_RE.match(basename):
        raise CommandRejected("command basename malformed")
    for i, arg in enumerate(args or []):
        if not isinstance(arg, str) or not _ARG_RE.match(arg):
            raise CommandRejected(f"args[{i}] contains banned characters")


def _safe_env(job_env: dict[str, str] | None) -> dict[str, str]:
    """Inherited env minus secrets + the job env minus loader/PATH overrides."""
    base = {k: v for k, v in os.environ.items() if not _SECRET_KEY_RE.search(k)}
    for k, v in (job_env or {}).items():
        if _BANNED_ENV_RE.match(k):
            continue
        base[k] = v
    return base


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
    try:
        validate_command(command, args)
    except CommandRejected as exc:
        return RunResult(
            exit_code=126,        # convention: 126 == rejected by allowlist
            duration_s=time.monotonic() - start,
            stdout_tail="",
            stderr_tail=f"pulse: command rejected by execution-boundary allowlist: {exc}",
            timed_out=False,
        )
    final_env = _safe_env(env)
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
