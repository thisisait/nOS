"""An operator task rings once when its condition comes true, and not again on the next tick.

Steps only the operator can take (re-seal the spore after a blank) lived in a chat list and got
forgotten (row operator-task-on-condition, 2026-11-05). tools/operator-tasks.py runs each declared
condition reader every Pulse tick; this pins its edge: false -> true writes exactly one inbox row,
the next tick none, an UNKNOWN reader none. Offline: a temp wing.db built from the real schema.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import sqlite3
import subprocess
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
TOOL = REPO / "tools/operator-tasks.py"
RESEAL = REPO / "tools/spore/reseal-due.py"
SCHEMA = REPO / "files/anatomy/wing/db/schema-extensions.sql"


def _db(tmp: pathlib.Path) -> pathlib.Path:
    ddl = re.search(r"CREATE TABLE IF NOT EXISTS notifications \(.*?\n\);", SCHEMA.read_text(), re.S)
    path = tmp / "wing.db"
    with sqlite3.connect(path) as con:
        con.executescript(ddl.group(0))
    return path


def _tick(db: pathlib.Path, tasks: pathlib.Path, *extra: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "WING_DB_PATH": str(db)}
    return subprocess.run([sys.executable, str(TOOL), "--tasks", str(tasks), *extra],
                          env=env, capture_output=True, text=True, timeout=60)


def _rows(db: pathlib.Path) -> list[tuple]:
    with sqlite3.connect(db) as con:
        return con.execute("SELECT severity, channels_json, superseded_at FROM notifications").fetchall()


def test_a_condition_turning_true_rings_exactly_once(tmp_path):
    db = _db(tmp_path)
    flag, done = tmp_path / "cond", tmp_path / "done"
    reader = tmp_path / "reader.py"  # exit 0 when the named file holds "1", 1 otherwise
    reader.write_text("import sys,pathlib;p=pathlib.Path(sys.argv[1]);"
                      "sys.exit(0 if p.exists() and p.read_text()=='1' else 1)")
    tasks = tmp_path / "tasks.yml"
    tasks.write_text(yaml.safe_dump({"tasks": [{
        "id": "t", "title": "do it", "command": "do-it",
        "condition": [str(reader), str(flag)], "done": [str(reader), str(done)]}]}))

    assert _tick(db, tasks, "--apply").returncode == 0 and _rows(db) == []
    flag.write_text("1")
    assert _tick(db, tasks).returncode == 0 and _rows(db) == [], "a dry run wrote"
    _tick(db, tasks, "--apply")
    _tick(db, tasks, "--apply")
    rows = _rows(db)
    assert len(rows) == 1, f"one true condition rang {len(rows)} times"
    assert rows[0][0] == "high" and "ntfy" in json.loads(rows[0][1]) and rows[0][2] is None

    done.write_text("1")
    _tick(db, tasks, "--apply")
    assert _rows(db)[0][2] is not None, "the done reader did not close the row"
    _tick(db, tasks, "--apply")
    assert len(_rows(db)) == 1, "condition and done both true: it rang again"
    done.write_text("0")
    _tick(db, tasks, "--apply")
    assert len(_rows(db)) == 2, "a new episode did not ring"


def test_an_unknown_reader_rings_nothing_and_says_so(tmp_path):
    db = _db(tmp_path)
    tasks = tmp_path / "tasks.yml"
    tasks.write_text(yaml.safe_dump({"tasks": [{
        "id": "t", "title": "x", "command": "x", "condition": ["/nonexistent/reader"], "done": ["/x"]}]}))
    out = _tick(db, tasks, "--apply")
    assert out.returncode == 2 and "UNKNOWN" in out.stdout and _rows(db) == []


def test_the_spore_reseal_reader(tmp_path):
    # Due = a blank newer than the last seal, nothing else: a backup-age term made it true only
    # 03:00-09:00, so it closed by day and rang again every night (review 11-05).
    nos = tmp_path / ".nos"
    nos.mkdir()
    env = {**os.environ, "HOME": str(tmp_path)}
    run = lambda *a: subprocess.run([sys.executable, str(RESEAL), *a], env=env,  # noqa: E731
                                    capture_output=True, text=True, timeout=60).returncode
    assert run() == 1 and run("--done") == 1, "no blank, no backup record: 'not due', not UNKNOWN"
    (nos / "blank-runs.jsonl").write_text('{"started": "2026-11-01T10:00:00Z"}\n')
    assert run() == 0 and run("--done") == 1, "a blank after no seal: due, whatever the backup says"
    (nos / "spore-seals.log").write_text("2026-11-02T10:00:00Z\n")
    assert run() == 1 and run("--done") == 0, "sealed after the blank: done"
    (nos / "blank-runs.jsonl").write_text("not json\n")
    assert run() == 2, "an unreadable blank record must read UNKNOWN"


def test_the_first_task_is_declared():
    tasks = yaml.safe_load((REPO / "state/operator-tasks.yml").read_text())["tasks"]
    ids = {t["id"] for t in tasks}
    assert "spore-reseal-after-backup" in ids
    for t in tasks:
        for reader in (t["condition"], t["done"]):
            assert (REPO / reader[0]).exists(), f"{t['id']}: reader {reader[0]} is missing"
