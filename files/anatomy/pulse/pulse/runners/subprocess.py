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
import signal
import subprocess
import time


# ── SEC H-PULSE1 (2026-05-24): execution-boundary command allowlist ──────────
# Ports PulsePresenter::validatePulseCommand into the runner that actually
# spawns the process, so the allowlist holds regardless of who wrote the
# pulse_jobs row (direct SQLite, agents, a future create-path) — not just the
# one PHP create endpoint. Keep in lockstep with the PHP constants.
# Until 2026-10-03 the prefixes were `/Users/` + `/home/`: ~/Downloads/x.py
# passed. Now only the trees the catalog renders jobs into (workload-allowlist).
# Until 2026-10-04 all of /opt/homebrew/bin/ + /usr/local/bin/ passed too, so any
# wrapper (docker, gtimeout, uv, pip3) ran a planted payload: binaries are NAMED.
_SYSTEM_BINARIES = ("/opt/homebrew/bin/php",)
_HOME_BINARIES = (".local/bin/frankenphp",)  # Linux Wing PHP
_REPO_TREES = ("tools/", "files/anatomy/scripts/", "files/anatomy/plugins/", "files/vuln-scan/")
_HOME_TREES = ("wing/", ".nos/")
#: An interpreter runs its first positional arg, so that arg is the real command.
_INTERPRETER_RE = re.compile(r"^(php|frankenphp|python[0-9.]*|node|ruby|perl)$")
#: Shells, and wrappers that exec another program. Naming one here is not enough
#: to allow it: it must also be added to _SYSTEM_BINARIES with a reason.
_BANNED_BASENAMES = frozenset((
    "bash", "bun", "bunx", "csh", "dash", "docker", "env", "fish", "gtimeout", "ksh",
    "nohup", "npm", "npx", "pip", "pip3", "sh", "su", "sudo", "timeout", "uv", "uvx",
    "xargs", "zsh"))
_BASENAME_RE = re.compile(r"^[a-z][a-zA-Z0-9._-]{0,63}$")
_ARG_RE = re.compile(r"^[a-zA-Z0-9._@/:=,+~-]{0,512}$")

# ── SEC M-PULSE2: child-env scoping ──────────────────────────────────────────
# Inherited env minus secrets; a job's OWN env is an allow-list of the keys
# declared jobs set (derived, pinned by test_pulse_command_allowlist) + the
# daemon's. The deny-list it replaced missed NODE_OPTIONS, PHP_INI_SCAN_DIR, PS4.
_SECRET_KEY_RE = re.compile(
    r"(SECRET|TOKEN|PASSWORD|CREDENTIAL|ANTHROPIC|HMAC|_KEY$|API_KEY)", re.I)
_JOB_ENV_KEYS = frozenset((
    "BONE_API_URL", "CORTEX_AGENT_TOKEN_CAPTURE", "CORTEX_AGENT_TOKEN_RO", "CORTEX_AGENT_TOKEN_RW",
    "CORTEX_API_URL", "DISPATCH_BATCH_LIMIT", "DISPATCH_DIGEST_FLUSH", "DISPATCH_MAIL_DIGEST_FLOOR",
    "DRIFT_STALE_HOURS", "GITLEAKS_MIN_SEVERITY", "KEAP_AGENT_TOKEN_CAPTURE", "KEAP_AGENT_TOKEN_RO",
    "KEAP_AGENT_TOKEN_RW", "KEAP_API_URL", "MAIL_FROM", "MAIL_HOST", "MAIL_PASSWORD", "MAIL_PORT",
    "MAIL_RECIPIENT", "MAIL_TLS_MODE", "MAIL_TLS_VERIFY", "MAIL_USERNAME", "N8N_API_KEY",
    "NOS_AGENT_CLIENT_ID", "NOS_AGENT_CLIENT_SECRET", "NOS_AGENT_NAME", "NOS_AGENT_PROFILE",
    "NOS_AGENT_TASK", "NOS_AUTHENTIK_URL", "NOS_CONSOLIDATE_DB_EXCLUDE", "NOS_CONSOLIDATE_FS_ROOTS",
    "NOS_COST_TALLY_FLOOR_USD", "NOS_COST_TALLY_WINDOW_H", "NOS_MARIADB_ROOT_PASSWORD",
    "NOS_NOTIFY_ACTOR", "NOS_NOTIFY_BIN", "NOS_NOTIFY_ORIGIN", "NOS_REPO", "NOS_SCAN_DIR",
    "NOS_TOFU_DIR", "NTFY_PUBLISH_PASSWORD", "NTFY_PUBLISH_USER", "NTFY_URL", "OLLAMA_URL",
    "PROMETHEUS_URL", "REPO_DIR", "VULNSCAN_SECURITY_DIR", "WING_API_TOKEN", "WING_API_URL",
    "WING_DATA_DIR", "WING_DB_PATH", "WING_EVENTS_HMAC_SECRET", "WING_EVENTS_HMAC_SECRET_RETIRED"))
_DAEMON_ENV_KEYS = frozenset(("PULSE_RUN_ID", "TRACEPARENT"))


def _root(var: str) -> str:
    v = os.environ.get(var, "").rstrip("/")
    return v + "/" if v.startswith("/") else ""


def _script_trees() -> tuple[str, ...]:
    """Repo trees under NOS_REPO_ROOT + home trees under HOME. Unset → none."""
    repo, home = _root("NOS_REPO_ROOT"), _root("HOME")
    return tuple([repo + t for t in _REPO_TREES if repo] + [home + t for t in _HOME_TREES if home])


def _allowed_binaries() -> tuple[str, ...]:
    """Exact paths. Mirrors PulsePresenter::allowedBinaries."""
    home = _root("HOME")
    return _SYSTEM_BINARIES + tuple(home + b for b in _HOME_BINARIES if home)


class CommandRejected(ValueError):
    """Raised when a job command/args fail the execution-boundary allowlist."""


def validate_command(command: str, args: list[str]) -> None:
    """Mirror of PulsePresenter::validatePulseCommand. Raises CommandRejected."""
    if not command or command[0] != "/":
        raise CommandRejected("command must be an absolute path")
    if "/../" in command + "/" or "/./" in command:
        raise CommandRejected("command path must be normalised (no . or .. segments)")
    if command not in _allowed_binaries() and not any(command.startswith(t) for t in _script_trees()):
        raise CommandRejected("command path not in Pulse allowlist")
    basename = os.path.basename(command)
    if basename in _BANNED_BASENAMES:
        raise CommandRejected(f"command basename {basename!r} is banned (shell or exec wrapper)")
    if not _BASENAME_RE.match(basename):
        raise CommandRejected("command basename malformed")
    for i, arg in enumerate(args or []):
        if not isinstance(arg, str) or not _ARG_RE.match(arg):
            raise CommandRejected(f"args[{i}] contains banned characters")
    if _INTERPRETER_RE.match(basename):
        rest = [a for a in (args or []) if a != "php-cli"]  # frankenphp's subcommand
        script = rest[0] if rest else ""
        if ("/../" in script + "/" or "/./" in script
                or not any(script.startswith(t) for t in _script_trees())):
            raise CommandRejected(f"{basename} must run a script from the Pulse trees, got {script!r}")


def _safe_env(job_env: dict[str, str] | None) -> dict[str, str]:
    """Inherited env minus secrets + the job env's allow-listed keys."""
    base = {k: v for k, v in os.environ.items() if not _SECRET_KEY_RE.search(k)}
    allowed = _JOB_ENV_KEYS | _DAEMON_ENV_KEYS
    base.update({k: v for k, v in (job_env or {}).items() if k in allowed})
    return base


@dataclasses.dataclass(frozen=True)
class RunResult:
    exit_code: int
    duration_s: float
    stdout_tail: str
    stderr_tail: str
    timed_out: bool


def _kill_tree(proc: subprocess.Popen) -> None:
    """SIGKILL the child's whole process group.

    `os.killpg` and not `proc.kill()`: the grandchild IS the point of this
    change. Guarded because the group can legitimately be gone already — the
    child may have exited between the timeout firing and this call, and a
    ProcessLookupError there is a race, not a failure.
    """
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        proc.kill()  # the group is gone or not ours; the direct child still is


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
        # THE TIMEOUT KILLS THE WHOLE TREE, NOT THE PROCESS WE HAPPEN TO HOLD.
        #
        # MEASURED 2026-08-31, twice in one night. `subprocess.run(timeout=)`
        # SIGKILLs the DIRECT child only. Every agent job's command is
        # tools/run-agent.sh, a bash wrapper whose real work is a `php
        # run-agent.php` grandchild, so the timeout killed the shell and left
        # the agent running:
        #
        #   librarian:brief-taxonomy   killed at 900s   session ended  1103s
        #   librarian:judge-lint-queue killed at 600s   session ended   627s
        #
        # Both sessions ended `outcome_satisfied`. The work COMPLETED, minutes
        # after the estate recorded it as killed — so pulse_runs said rc=-9
        # while agent_sessions said satisfied, and neither was wrong about what
        # it saw. That is two truths from one run, which is the shape this
        # estate keeps paying for.
        #
        # The second-order cost is worse than the bookkeeping. The agent mutex
        # is released by `trap 'nos_agent_lock_release' EXIT` in
        # agent-run-lock.sh, and SIGKILL does not run traps. So the killed
        # wrapper leaked its slot: measured at 07:38 the same morning, slot.1
        # was still held by PID 51683 (dead since 05:38) — and a leaked slot is
        # what makes the NEXT agent job wait 300s and exit 2, the failure that
        # was diagnosed the day before as a scheduling collision and fixed by
        # moving two cron times. That fix was right on its own terms and this
        # is the generator underneath it.
        #
        # start_new_session puts the child in its own process group; killing
        # the GROUP reaches the grandchild. The wrapper still cannot run its
        # trap — SIGKILL never allows that — so the lock's PID-liveness reclaim
        # remains the backstop, and now it has at most one dead PID to reclaim
        # instead of a live agent to fight.
        proc = subprocess.Popen(
            [command, *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=final_env,
            cwd=cwd,
            start_new_session=True,
        )
        try:
            out, err = proc.communicate(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
            # After the group is gone, collect whatever it had written. A
            # second timeout here would mean a process ignoring SIGKILL, which
            # is not a thing on this platform — but it is bounded anyway so a
            # stuck read can never wedge the daemon's tick.
            try:
                out, err = proc.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                out, err = "", ""
            return RunResult(
                exit_code=-9,     # convention: -9 == SIGKILL after timeout
                duration_s=time.monotonic() - start,
                stdout_tail=out or "",
                stderr_tail=err or "",
                timed_out=True,
            )
        duration = time.monotonic() - start
        return RunResult(
            exit_code=proc.returncode,
            duration_s=duration,
            stdout_tail=out or "",
            stderr_tail=err or "",
            timed_out=False,
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
