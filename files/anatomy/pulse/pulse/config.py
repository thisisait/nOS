"""Pulse runtime configuration — read from env vars with sensible defaults.

The launchd plist sets these vars; in dev mode you can export them yourself
and run ``python -m pulse`` directly.
"""

from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass


@dataclass(frozen=True)
class PulseConfig:
    """Immutable runtime config snapshot."""

    wing_api_base: str
    wing_api_token: str
    tick_interval_s: float
    state_dir: pathlib.Path
    log_path: pathlib.Path
    max_concurrent_runs: int
    dry_run: bool

    @classmethod
    def from_env(cls) -> "PulseConfig":
        home = pathlib.Path(os.path.expanduser("~"))
        state_dir = pathlib.Path(os.environ.get(
            "PULSE_STATE_DIR", str(home / "pulse" / "state")))
        log_path = pathlib.Path(os.environ.get(
            "PULSE_LOG_PATH", str(home / "pulse" / "log" / "pulse.log")))
        return cls(
            wing_api_base=os.environ.get(
                "WING_API_BASE", "http://127.0.0.1:9000"),
            wing_api_token=os.environ.get("WING_API_TOKEN", ""),
            tick_interval_s=float(os.environ.get("PULSE_TICK_INTERVAL_S", "30")),
            state_dir=state_dir,
            log_path=log_path,
            max_concurrent_runs=int(os.environ.get("PULSE_MAX_CONCURRENT", "4")),
            dry_run=os.environ.get("PULSE_DRY_RUN", "0") == "1",
        )

    def ensure_dirs(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
