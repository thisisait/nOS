"""Unit tests for pulse.daemon — tick + dispatch logic.

We mock the WingClient so no HTTP is involved; we mock subprocess.execute
to avoid actually forking. The daemon's ``run()`` main loop isn't tested
here (it's a sleep-bounded outer loop); we exercise ``tick()`` and
``_dispatch()`` directly.
"""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

import pytest

from pulse.config import PulseConfig
from pulse.daemon import PulseDaemon
from pulse.runners.subprocess import RunResult


def make_config(**overrides) -> PulseConfig:
    """PulseConfig with sensible test defaults."""
    base = dict(
        wing_api_base="http://127.0.0.1:9000",
        wing_api_token="test-token",
        tick_interval_s=30.0,
        state_dir=__import__("pathlib").Path("/tmp/pulse-test-state"),
        log_path=__import__("pathlib").Path("/tmp/pulse-test.log"),
        max_concurrent_runs=4,
        dry_run=False,
    )
    base.update(overrides)
    return PulseConfig(**base)


# ── tick() — empty case ────────────────────────────────────────────────

def test_tick_no_due_jobs_returns_zero():
    cfg = make_config()
    wing = MagicMock()
    wing.list_due_jobs.return_value = []
    d = PulseDaemon(cfg, wing=wing)
    assert d.tick() == 0
    wing.list_due_jobs.assert_called_once()


# ── _dispatch() — validation ───────────────────────────────────────────

def test_dispatch_rejects_missing_command():
    cfg = make_config()
    wing = MagicMock()
    d = PulseDaemon(cfg, wing=wing)
    assert d._dispatch({"id": "job1", "runner": "subprocess"}) is False


def test_dispatch_rejects_unsupported_runner():
    """A4 PoC: only 'subprocess' supported. 'agent' (A8) skipped with warning."""
    cfg = make_config()
    wing = MagicMock()
    d = PulseDaemon(cfg, wing=wing)
    assert d._dispatch({"id": "job1", "runner": "agent",
                        "command": "/bin/true"}) is False


def test_dispatch_rejects_non_list_args():
    cfg = make_config()
    wing = MagicMock()
    d = PulseDaemon(cfg, wing=wing)
    assert d._dispatch({"id": "job1", "command": "/bin/true",
                        "args": "not-a-list"}) is False


# ── _dispatch() — happy path with dry-run ──────────────────────────────

def test_dispatch_dry_run_completes_without_subprocess(tmp_path):
    """Dry run mode: no subprocess.execute() called, both wing endpoints fired."""
    cfg = make_config(dry_run=True, state_dir=tmp_path,
                      log_path=tmp_path / "p.log")
    wing = MagicMock()
    wing.list_due_jobs.return_value = []
    d = PulseDaemon(cfg, wing=wing)
    job = {"id": "test-job", "command": "/bin/true",
           "args": [], "max_runtime_s": 5}
    assert d._dispatch(job) is True
    # Wait for worker thread to complete
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        with d._inflight_lock:
            if not d._inflight:
                break
        time.sleep(0.05)
    wing.post_run_start.assert_called_once()
    wing.post_run_finish.assert_called_once()
    finish_kwargs = wing.post_run_finish.call_args.kwargs
    assert finish_kwargs["exit_code"] == 0
    assert finish_kwargs["stdout_tail"] == "dry-run"


# ── tick() — concurrency cap ───────────────────────────────────────────

def test_tick_respects_concurrency_cap():
    """When inflight == max_concurrent, tick returns 0 without polling."""
    cfg = make_config(max_concurrent_runs=2)
    wing = MagicMock()
    d = PulseDaemon(cfg, wing=wing)
    # Pre-populate inflight set with sentinel threads
    sentinel1 = threading.Thread(target=lambda: None)
    sentinel2 = threading.Thread(target=lambda: None)
    d._inflight = {sentinel1, sentinel2}
    assert d.tick() == 0
    wing.list_due_jobs.assert_not_called()


# ── tick() — partial fire under cap ────────────────────────────────────

def test_tick_fires_only_up_to_free_slots(tmp_path):
    """3 due jobs but only 2 free slots → fire 2."""
    cfg = make_config(max_concurrent_runs=2, dry_run=True,
                      state_dir=tmp_path, log_path=tmp_path / "p.log")
    wing = MagicMock()
    wing.list_due_jobs.return_value = [
        {"id": "j1", "command": "/bin/true", "args": [], "max_runtime_s": 5},
        {"id": "j2", "command": "/bin/true", "args": [], "max_runtime_s": 5},
        {"id": "j3", "command": "/bin/true", "args": [], "max_runtime_s": 5},
    ]
    d = PulseDaemon(cfg, wing=wing)
    fired = d.tick()
    assert fired == 2


# ── stop() — drain semantics ───────────────────────────────────────────

def test_stop_with_no_inflight_returns_immediately():
    cfg = make_config()
    wing = MagicMock()
    d = PulseDaemon(cfg, wing=wing)
    start = time.monotonic()
    d.stop(drain_s=10.0)
    assert time.monotonic() - start < 1.0  # didn't actually wait 10s


# ── PulseConfig.from_env() ─────────────────────────────────────────────

def test_config_from_env_defaults(monkeypatch):
    """Empty env → defaults."""
    for var in ("WING_API_BASE", "WING_API_TOKEN", "PULSE_TICK_INTERVAL_S",
                "PULSE_MAX_CONCURRENT", "PULSE_DRY_RUN"):
        monkeypatch.delenv(var, raising=False)
    cfg = PulseConfig.from_env()
    assert cfg.wing_api_base == "http://127.0.0.1:9000"
    assert cfg.wing_api_token == ""
    assert cfg.tick_interval_s == 30.0
    assert cfg.max_concurrent_runs == 4
    assert cfg.dry_run is False


def test_config_from_env_overrides(monkeypatch):
    monkeypatch.setenv("WING_API_BASE", "http://example.com")
    monkeypatch.setenv("WING_API_TOKEN", "secret")
    monkeypatch.setenv("PULSE_TICK_INTERVAL_S", "5")
    monkeypatch.setenv("PULSE_MAX_CONCURRENT", "8")
    monkeypatch.setenv("PULSE_DRY_RUN", "1")
    cfg = PulseConfig.from_env()
    assert cfg.wing_api_base == "http://example.com"
    assert cfg.wing_api_token == "secret"  # noqa: S105
    assert cfg.tick_interval_s == 5.0
    assert cfg.max_concurrent_runs == 8
    assert cfg.dry_run is True
