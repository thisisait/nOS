#!/usr/bin/env python3
"""Ring the operator once when a declared task's condition comes true.

A task (state/operator-tasks.yml) is a step only the operator can take, and only after
something else happens. Each tick runs its `condition` reader: exit 0 = true, 1 = false,
anything else = UNKNOWN. True with no open inbox row for the task inserts exactly one
(supersede_key operator-task:<id>); the next tick sees it open and stays silent. The row
closes (superseded_at) when its `done` reader exits 0, or once read by the operator and the
condition is false again; the next true condition then rings again. HIGH reaches ntfy through
files/anatomy/wing/bin/dispatch-notifications.php, which already forwards it.

    tools/operator-tasks.py            # dry run: what each condition says, writes nothing
    tools/operator-tasks.py --apply    # the Pulse job (wing-base:operator-tasks)

Exit 0 every condition read; 2 at least one was UNKNOWN (Pulse's state-change alarm says so).
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sqlite3
import subprocess
import sys
import uuid
from datetime import datetime, timezone

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
TASKS = REPO / "state" / "operator-tasks.yml"


def read(argv: list[str]) -> bool | None:
    """Run a repo-relative reader; True/False on exit 0/1, None for anything else."""
    cmd = [str(REPO / argv[0]), *argv[1:]]
    if cmd[0].endswith(".py"):
        cmd.insert(0, sys.executable)
    try:
        rc = subprocess.run(cmd, cwd=REPO, capture_output=True, timeout=120).returncode
    except (OSError, subprocess.SubprocessError):
        return None
    return {0: True, 1: False}.get(rc)


def tick(db: sqlite3.Connection, task: dict, apply: bool) -> str:
    key = f"operator-task:{task['id']}"
    row = db.execute(
        "SELECT uuid, wing_inbox_read_at FROM notifications WHERE supersede_key = ? AND "
        "target_actor_id = 'operator' AND superseded_at IS NULL ORDER BY id DESC LIMIT 1", (key,)
    ).fetchone()
    if row is not None:
        # Unread closes on `done`; read (the operator's word) closes once the condition is false.
        if (read(task["done"]) if row[1] is None else read(task["condition"]) is False):
            if apply:
                db.execute("UPDATE notifications SET superseded_at = ? WHERE uuid = ?",
                           (datetime.now(timezone.utc).isoformat(), row[0]))
            return "closed"
        return "open"
    cond = read(task["condition"])
    if cond is None:
        return "UNKNOWN"
    if not cond or read(task["done"]):  # done already: ringing would flap ring/close every tick
        return "waiting"
    if apply:
        sev = task.get("severity", "high")
        db.execute(
            "INSERT INTO notifications (uuid, severity, title, body, actor_id, target_actor_id, "
            "origin_plugin, channels_json, metadata_json, supersede_key) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), sev, task["title"], f"Run: {task['command']}",
             key, "operator", "operator-tasks",
             json.dumps(["wing-inbox", "ntfy"] if sev in ("critical", "high") else ["wing-inbox"]),
             json.dumps({"task_id": task["id"], "click_url": "/inbox"}), key),
        )
    return "RANG"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true", help="write the inbox rows (default: dry run)")
    ap.add_argument("--tasks", type=pathlib.Path, default=TASKS)
    args = ap.parse_args()
    tasks = (yaml.safe_load(args.tasks.read_text(encoding="utf-8")) or {}).get("tasks") or []
    path = os.environ.get("WING_DB_PATH") or str(pathlib.Path.home() / "wing/app/data/wing.db")
    db = sqlite3.connect(f"file:{path}?mode={'rw' if args.apply else 'ro'}", uri=True, timeout=5)
    unknown = False
    with db:
        for task in tasks:
            verdict = tick(db, task, args.apply)
            unknown |= verdict == "UNKNOWN"
            print(f"{verdict:8} {task['id']}{'' if args.apply else ' (dry run)'}")
    db.close()
    return 2 if unknown else 0


if __name__ == "__main__":
    sys.exit(main())
