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
        timeout_s = float(job.get("max_runtime_s", 300))
        run_id = str(uuid.uuid4())
        # Spawn worker thread (subprocess.run blocks; we don't want to
        # block the tick loop while a 5-minute backup runs).
        t = threading.Thread(
            target=self._run_in_thread,
            args=(job_id, run_id, command, args, timeout_s),
            name=f"pulse-run-{job_id[:8]}",
            daemon=False,  # don't kill mid-run on stop; drain instead
        )
        with self._inflight_lock:
            self._inflight.add(t)
        t.start()
        return True

    def _run_in_thread(self, job_id: str, run_id: str,
                       command: str, args: list, timeout_s: float) -> None:
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
            result = sp_runner.execute(command, args, timeout_s=timeout_s)
            log.info("job %s done rc=%d dur=%.1fs timed_out=%s",
                     job_id, result.exit_code, result.duration_s, result.timed_out)
            self.wing.post_run_finish(
                run_id, finished_at_iso=_now_iso(),
                exit_code=result.exit_code,
                stdout_tail=result.stdout_tail,
                stderr_tail=result.stderr_tail,
            )
        except Exception as e:  # noqa: BLE001 — broad catch on purpose; logged
            log.exception("job %s fatal: %s", job_id, e)
            try:
                self.wing.post_run_finish(
                    run_id, finished_at_iso=_now_iso(),
                    exit_code=255,
                    stdout_tail="",
                    stderr_tail=f"daemon exception: {e}",
                )
            except Exception:  # noqa: BLE001
                pass
        finally:
            with self._inflight_lock:
                self._inflight.discard(thread)

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
