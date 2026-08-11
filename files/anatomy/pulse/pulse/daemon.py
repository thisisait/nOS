"""Pulse daemon — tick loop.

Architecture (per docs/bones-and-wings-refactor.md §4.4):

1. Every ``tick_interval_s`` (default 30s), poll Wing API for due jobs.
2. For each due job: emit ``run_start`` event, fork-and-exec via the
   runner, capture result, emit ``run_finish`` event with exit_code.
3. Concurrency cap: ``max_concurrent_runs`` (default 4). When at cap, the
   tick logs and skips remaining due jobs — they'll be picked up on the
   next tick (no queue, no starvation since due_at sort is stable).
4. SIGTERM handler: drains in-flight runs (up to 30s grace) before
   exiting cleanly. launchd's KeepAlive will respawn us if we hard-die.

A4 scope: non-agentic only. Job's ``runner`` field MUST be "subprocess".
A8 will add agent runner; daemon dispatches by ``runner`` field.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import signal
import sys
import threading
import time
import uuid
from datetime import datetime, timezone

from . import redact
from .config import PulseConfig
from .runners import subprocess as sp_runner
from .wing_client import WingClient

log = logging.getLogger("pulse")


# ── helpers ─────────────────────────────────────────────────────────────

def _setup_logging(log_path) -> None:
    log.setLevel(logging.INFO)
    handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=10 * 1024 * 1024, backupCount=5)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s"))
    log.addHandler(handler)
    # Also mirror to stderr so launchd captures it for status visibility
    err_h = logging.StreamHandler(sys.stderr)
    err_h.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s"))
    log.addHandler(err_h)


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")


# ── daemon ──────────────────────────────────────────────────────────────

class PulseDaemon:
    """Event-loop free single-threaded daemon with bounded thread-pool for runs."""

    def __init__(self, config: PulseConfig, wing: WingClient | None = None):
        self.config = config
        self.wing = wing or WingClient(config.wing_api_base, config.wing_api_token)
        self._stop = threading.Event()
        self._inflight: set[threading.Thread] = set()
        # job_id -> thread. `_inflight` alone cannot answer "is THIS job already
        # running?", and Wing only advances next_fire_at when a run FINISHES —
        # so a job that outlives one tick stays due and is dispatched again.
        # pulse_jobs.max_concurrent has defaulted to 1 since the schema was
        # written; this is where that column is finally honoured.
        self._inflight_jobs: dict[str, threading.Thread] = {}
        self._inflight_lock = threading.Lock()

    # ── lifecycle ───────────────────────────────────────────────────────

    def stop(self, drain_s: float = 30.0) -> None:
        """Signal stop + wait up to drain_s for in-flight runs."""
        log.info("stop requested; draining (%ds grace)", drain_s)
        self._stop.set()
        deadline = time.monotonic() + drain_s
        while time.monotonic() < deadline:
            with self._inflight_lock:
                if not self._inflight:
                    log.info("no in-flight runs; exiting clean")
                    return
                count = len(self._inflight)
            log.info("waiting for %d in-flight run(s)", count)
            time.sleep(1.0)
        log.warning("drain timeout; forcing exit with in-flight runs")

    # ── tick ────────────────────────────────────────────────────────────

    def tick(self) -> int:
        """One iteration. Returns count of jobs fired this tick."""
        with self._inflight_lock:
            free_slots = self.config.max_concurrent_runs - len(self._inflight)
        if free_slots <= 0:
            log.info("at concurrency cap (%d); skipping tick",
                     self.config.max_concurrent_runs)
            return 0
        due = self.wing.list_due_jobs()
        if not due:
            return 0
        log.info("tick: %d due, %d slots free", len(due), free_slots)
        fired = 0
        for job in due[:free_slots]:
            if self._dispatch(job):
                fired += 1
        return fired

    def _dispatch(self, job: dict) -> bool:
        """Validate + fire one job. Returns True if fired (regardless of
        exit_code), False if rejected (validation, unknown runner, etc.).
        """
        job_id = str(job.get("id", "?"))
        # Re-entrancy guard. next_fire_at only moves on finish, so every job
        # whose runtime exceeds the tick interval is still due on the next tick.
        # Measured 2026-07-28: conductor:vulnerability-scan (~500s, 30s ticks)
        # was dispatched twice every single night; only its own PID lockfile kept
        # the duplicate from running the scan concurrently, and the duplicate's
        # instant exit is what advanced next_fire_at and ended the storm. A job
        # without that lockfile would simply have run twice at once.
        with self._inflight_lock:
            running = self._inflight_jobs.get(job_id)
        if running is not None and running.is_alive():
            log.info("job %s already in flight; not re-dispatching", job_id)
            return False
        runner = job.get("runner", "subprocess")
        if runner != "subprocess":
            # A8 will add "agent". For now, log + skip rather than crash.
            log.warning("job %s: unsupported runner %r (A4 PoC = subprocess only)",
                        job_id, runner)
            return False
        command = job.get("command")
        if not isinstance(command, str) or not command:
            log.warning("job %s: missing/invalid command", job_id)
            return False
        args = job.get("args") or []
        if not isinstance(args, list):
            log.warning("job %s: args must be list, got %r", job_id, type(args))
            return False
        env = job.get("env") or {}
        if not isinstance(env, dict):
            log.warning("job %s: env must be dict, got %r — ignoring", job_id, type(env))
            env = {}
        # SEC L-PULSE1 (2026-05-24): clamp to a host ceiling so a job can't pin
        # a run slot (and stall the 30s stop-drain) with an absurd timeout.
        timeout_s = min(float(job.get("max_runtime_s", 300)), 3600.0)
        run_id = str(uuid.uuid4())
        # Spawn worker thread (subprocess.run blocks; we don't want to
        # block the tick loop while a 5-minute backup runs).
        t = threading.Thread(
            target=self._run_in_thread,
            args=(job_id, run_id, command, args, timeout_s, env),
            name=f"pulse-run-{job_id[:8]}",
            daemon=False,  # don't kill mid-run on stop; drain instead
        )
        with self._inflight_lock:
            self._inflight.add(t)
            self._inflight_jobs[job_id] = t
        t.start()
        return True

    #: What a stored env value looks like when it is a POINTER rather than a
    #: value. Deliberately one scheme, not AgentKit's two: `infisical:` would
    #: mean this daemon holds a vault credential, which is the thing it is
    #: trying to stop holding.
    SECRET_PREFIX = "secret:"

    def _resolve_secrets(self, env: dict) -> dict:
        """`secret:wing_api_token` → the value from ~/.nos/secrets.yml (0600).

        A REFERENCE THAT CANNOT BE RESOLVED FAILS THE JOB. Passing the literal
        `secret:foo` through would hand a subprocess a string shaped like a
        token: the call would 401, the job would report a plausible upstream
        error, and the actual fault — a name that is not in the store — would be
        invisible. Refusing names it.

        Literals pass through untouched, so this can land before the catalog
        stops emitting them; a job is migrated when its value becomes a
        reference, one at a time, with the rest still running.
        """
        refs = {k: v for k, v in env.items()
                if isinstance(v, str) and v.startswith(self.SECRET_PREFIX)}
        if not refs:
            return env

        store = self._secret_store()
        out = dict(env)
        missing = []
        for key, ref in refs.items():
            name = ref[len(self.SECRET_PREFIX):]
            # PRESENCE, not truthiness. `mail_password` is legitimately '' on an
            # estate using mailpit rather than Stalwart, and the first cut of
            # this check treated an empty value as an absent name — which would
            # have refused every notification job on a correctly-configured
            # host. Declared-and-empty is an answer; not declared is a fault.
            if name not in store:
                missing.append(f"{key} -> {name}")
                continue
            out[key] = str(store[name] if store[name] is not None else '')
        if missing:
            raise RuntimeError(
                "unresolvable secret reference(s): " + ", ".join(missing)
                + f" (store: {self._secrets_path()}). The job was NOT run — a "
                "literal 'secret:…' reaching a subprocess would look like a "
                "credential and fail as one somewhere else."
            )
        return out

    def _secrets_path(self):
        import pathlib as _pathlib
        return _pathlib.Path.home() / ".nos/secrets.yml"

    def _secret_store(self) -> dict:
        """Read per resolution, not cached.

        A converge rewrites this file; a daemon holding a parsed copy from boot
        would authenticate with a rotated-away value and report the upstream's
        refusal as the fault. The file is small and this runs once per job.
        """
        path = self._secrets_path()
        if not path.is_file():
            return {}
        try:
            import yaml
            return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception as exc:                                  # noqa: BLE001
            log.error("could not read %s: %s", path, exc)
            return {}

    def _run_in_thread(self, job_id: str, run_id: str,
                       command: str, args: list, timeout_s: float,
                       env: dict[str, str] | None = None) -> None:
        thread = threading.current_thread()
        try:
            self.wing.post_run_start(job_id, run_id, _now_iso())
            log.info("job %s start (run_id=%s)", job_id, run_id)
            if self.config.dry_run:
                log.info("DRY RUN: would exec %s %r", command, args)
                self.wing.post_run_finish(run_id, finished_at_iso=_now_iso(),
                                          exit_code=0,
                                          stdout_tail="dry-run",
                                          stderr_tail="")
                return
            # SECRETS ARE RESOLVED HERE, not stored resolved.
            #
            # MEASURED 2026-08-11: 19 of 29 rows in `pulse_jobs` carried a
            # derived secret in `env_json` IN THE CLEAR — client secrets,
            # `KEAP_AGENT_TOKEN_RW`, `WING_EVENTS_HMAC_SECRET`, every one of them
            # `<prefix>_pw_*`, so a single row also reveals the prefix that
            # yields the rest by construction. SEC-9 already scrubs subprocess
            # OUTPUT; nothing addressed the values at rest, and wing.db is read
            # by anything running as this UID.
            #
            # AgentKit has said the answer since A14 — `agent_credentials.
            # secret_ref` is a POINTER (`env:VAR`, `infisical:/path`) resolved at
            # session-open, never a value — and the runtime that actually runs
            # the agents did the opposite. This closes that gap on the Pulse side.
            env = self._resolve_secrets(env or {})
            result = sp_runner.execute(command, args, timeout_s=timeout_s, env=env)
            log.info("job %s done rc=%d dur=%.1fs timed_out=%s",
                     job_id, result.exit_code, result.duration_s, result.timed_out)
            # SEC-9 (2026-05-23): scrub stdout/stderr tails BEFORE
            # forwarding to Wing. Subprocess output can carry env-var
            # dumps (WING_API_TOKEN=…), CLI password flags, Bearer
            # headers from HTTP-client tracebacks, and gitleaks
            # captured-secret previews. Without this, those values
            # persist into wing.db.events + /audit + launchd.err.log.
            # duration_ms is reported ONLY here, by the branch that ran the
            # subprocess and timed it. The dry-run and daemon-exception calls
            # below deliberately omit it: neither measured anything, and a 0
            # would read as an instant run rather than an absent one.
            self.wing.post_run_finish(
                run_id, finished_at_iso=_now_iso(),
                exit_code=result.exit_code,
                stdout_tail=redact.scrub_text(result.stdout_tail),
                stderr_tail=redact.scrub_text(result.stderr_tail),
                duration_ms=round(result.duration_s * 1000),
            )
        except Exception as e:  # noqa: BLE001 — broad catch on purpose; logged
            log.exception("job %s fatal: %s", job_id, e)
            try:
                self.wing.post_run_finish(
                    run_id, finished_at_iso=_now_iso(),
                    exit_code=255,
                    stdout_tail="",
                    stderr_tail=redact.scrub_text(f"daemon exception: {e}"),
                )
            except Exception:  # noqa: BLE001
                pass
        finally:
            with self._inflight_lock:
                self._inflight.discard(thread)
                # Only clear the guard if it still points at THIS thread — never
                # drop a successor's claim.
                if self._inflight_jobs.get(job_id) is thread:
                    del self._inflight_jobs[job_id]

    # ── main loop ───────────────────────────────────────────────────────

    def run(self) -> int:
        """Main loop. Returns process exit code."""
        signal.signal(signal.SIGTERM, lambda *_: self.stop())
        signal.signal(signal.SIGINT, lambda *_: self.stop())
        log.info("pulse v%s starting (wing=%s tick=%.0fs concurrency=%d dry_run=%s)",
                 _pkg_version(), self.config.wing_api_base,
                 self.config.tick_interval_s, self.config.max_concurrent_runs,
                 self.config.dry_run)
        last_warn_about_token = 0.0
        while not self._stop.is_set():
            if not self.config.wing_api_token:
                # No token = idle-tick. Warn once a minute, not every tick.
                now = time.monotonic()
                if now - last_warn_about_token > 60:
                    log.warning("WING_API_TOKEN not set; idling (no jobs polled)")
                    last_warn_about_token = now
            else:
                try:
                    self.tick()
                except Exception as e:  # noqa: BLE001
                    log.exception("tick fatal: %s", e)
            self._stop.wait(self.config.tick_interval_s)
        return 0


def _pkg_version() -> str:
    try:
        from . import __version__
        return __version__
    except ImportError:
        return "?"
