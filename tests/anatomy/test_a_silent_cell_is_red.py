"""An immune cell silent past its heartbeat is red (ssot/doctrine/immune-system.md §4.1).

WHY. The heartbeat was free text ('nightly, through the patrol') and red-status never
read it, so a killed or rewritten patrol went quiet with nothing saying so. Now each
heartbeat is `every_hours` + `last_report: pulse:<job>`; red-status reads pulse_runs and
names the cell. An unreadable registry is UNKNOWN, never green.
"""

from __future__ import annotations

import importlib.util
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]


def _red():
    spec = importlib.util.spec_from_file_location("_red_heartbeats", REPO / "tools/red-status.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _beat(job: str, hours: int = 26) -> dict:
    return {"heartbeat": {"every_hours": hours, "last_report": f"pulse:{job}"}}


def test_a_cell_silent_past_its_heartbeat_is_named(tmp_path):
    now = datetime.now(timezone.utc)
    at = lambda h: (now - timedelta(hours=h)).isoformat(timespec="seconds")  # noqa: E731
    reg = tmp_path / "indicators.yml"
    reg.write_text(yaml.safe_dump({"indicators": {
        "p:fresh": _beat("p:fresh"), "p:silent": _beat("p:silent"), "p:never": _beat("p:never"),
        "p:newborn": _beat("p:newborn"), "p:paused": _beat("p:paused"), "p:gone": _beat("p:gone"),
        "p:absent": _beat("p:absent"), "sentinel": {"heartbeat": "none (read on every red-status run)"},
    }}))
    db = tmp_path / "wing.db"
    with sqlite3.connect(db) as seed:
        seed.execute("CREATE TABLE pulse_jobs (id TEXT, paused INTEGER, created_at TEXT, removed_at TEXT, paused_reason TEXT)")
        seed.execute("CREATE TABLE pulse_runs (job_id TEXT, fired_at TEXT)")
        seed.executemany("INSERT INTO pulse_jobs VALUES (?,?,?,?,?)", [
            ("p:fresh", 0, at(500), None, None), ("p:silent", 0, at(500), None, None),
            ("p:never", 0, at(500), None, None), ("p:newborn", 0, at(2), None, None),
            ("p:paused", 1, at(500), None, "operator: noisy"), ("p:gone", 0, at(500), at(100), None),
        ])
        seed.executemany("INSERT INTO pulse_runs VALUES (?,?)", [
            ("p:fresh", at(30)), ("p:fresh", at(3)), ("p:silent", at(30)), ("p:paused", at(300)),
        ])
    red = _red()
    beats = red.heartbeats(reg)
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        silent = red.silent_cells(conn, beats)
        held = red.held_cells(conn, beats)
    finally:
        conn.close()
    assert [c["cell"] for c in silent] == ["p:never", "p:silent"], silent
    lines = red.reds({"silent_cells": silent})
    assert any("p:silent" in ln and "heartbeat" in ln for ln in lines), lines
    # a paused cell is a hold made visible, not hidden; a removed one is uninstalled = absent
    assert [c["cell"] for c in held] == ["p:paused"], held
    assert any("p:paused" in ln and "operator: noisy" in ln for ln in red.reds({"held_cells": held}))


def test_one_line_per_cause():
    """Measured 2026-11-05: Pulse down + 8 silent patrols printed 9 lines; Pulse up + 8 stuck printed 16."""
    red = _red()
    od = [{"job": f"p:{i}", "due_at": "x", "overdue_by": "1 h", "schedule": "0 3 * * *"} for i in range(3)]
    cells = [{"cell": f"p:{i}", "job": f"p:{i}", "every_hours": 26, "age": "2 d ago"} for i in range(4)]
    down = red.reds({"pulse": {"running": False, "how": "launchd: not loaded"},
                     "overdue_jobs": od, "silent_cells": cells})
    assert len(down) == 1 and "Pulse is not running" in down[0], down
    up = red.reds({"pulse": {"running": True, "how": "launchd"}, "overdue_jobs": od, "silent_cells": cells})
    assert len(up) == 4, up  # 3 overdue + the one silent cell only it can see (p:3)
    assert sum("p:3" in ln for ln in up) == 1, up


def test_an_unreadable_registry_is_unknown_not_green(tmp_path):
    red = _red()
    assert red.heartbeats(tmp_path / "missing.yml") is None
    bad = tmp_path / "bad.yml"
    bad.write_text(yaml.safe_dump({"indicators": {"p:x": {"heartbeat": {"every_hours": 26}}}}))
    assert red.heartbeats(bad) is None


def test_every_scheduled_cell_reports_through_its_own_job():
    reg = yaml.safe_load((REPO / "state/immune/indicators.yml").read_text(encoding="utf-8"))["indicators"]
    wrong = [k for k, v in reg.items() if v["kind"] in ("patrol", "verdicts")
             and (v["heartbeat"] if isinstance(v["heartbeat"], dict) else {}).get("last_report") != f"pulse:{k}"]
    assert not wrong, "scheduled cells whose heartbeat is not their own Pulse job: " + ", ".join(wrong)
