"""Pulse entry point — invoked by launchd via ``python -m pulse``."""

from __future__ import annotations

import os
import sqlite3
import sys

from .config import PulseConfig
from .daemon import PulseDaemon, _setup_logging


def anchor_wing_wal(path: str | None) -> sqlite3.Connection | None:
    """Second wing.db WAL anchor (Bone holds the first: bone/clients/wing.py
    anchor_wal), so a Bone restart leaves `mode=ro` readers their -shm.
    mode=rw never creates a missing wing.db. Gate:
    tests/anatomy/test_wing_db_ro_open_survives_missing_shm.py."""
    try:
        conn = sqlite3.connect(f"file:{path}?mode=rw", uri=True) if path else None
        if conn:
            conn.setconfig(sqlite3.SQLITE_DBCONFIG_NO_CKPT_ON_CLOSE, True)
            conn.execute("SELECT 1 FROM sqlite_master").fetchall()   # creates the sidecars
        return conn
    except Exception:  # noqa: BLE001 — no wing.db yet must not stop Pulse ticking
        return None


def main(argv: list[str] | None = None) -> int:
    cfg = PulseConfig.from_env()
    cfg.ensure_dirs()
    _setup_logging(cfg.log_path)
    wal_anchor = anchor_wing_wal(os.environ.get("WING_DB_PATH"))  # noqa: F841 — held for life
    daemon = PulseDaemon(cfg)
    return daemon.run()


if __name__ == "__main__":
    sys.exit(main())
