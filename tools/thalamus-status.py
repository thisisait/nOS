#!/usr/bin/env python3
"""Is the thalamus up, and what did it last do?

Reads the socket (~/.nos/thalamus.sock: a socket, mode 0600), the launchd job
(eu.thisisait.nos.thalamus), the ledger (~/thalamus/data/ledger.db, its dir 0700)
and the ledger's last session. Each line is OK / RED / UNKNOWN with its source.

Reads only. Exit 0 always. A source it cannot read is UNKNOWN, never green.
`--tags thalamus,verify` fails on any line that is not OK.

Usage:
    tools/thalamus-status.py [--json]
Env (tests): NOS_THALAMUS_SOCKET, NOS_THALAMUS_LEDGER.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import pathlib
import sqlite3
import stat
import subprocess
import sys

OK, RED, UNKNOWN = "OK", "RED", "UNKNOWN"
HOME = pathlib.Path.home()
LABEL = "eu.thisisait.nos.thalamus"


def line(check: str, state: str, detail: str, source: str) -> dict:
    return {"check": check, "state": state, "detail": detail, "source": source}


def judge_socket(path: pathlib.Path) -> dict:
    try:
        st = path.lstat()
    except FileNotFoundError:
        return line("socket", RED, "absent — the daemon is not serving", str(path))
    except OSError as exc:
        return line("socket", UNKNOWN, f"unreadable ({type(exc).__name__})", str(path))
    if not stat.S_ISSOCK(st.st_mode):
        return line("socket", RED, "not a socket", str(path))
    mode = stat.S_IMODE(st.st_mode)
    return line("socket", OK if mode == 0o600 else RED, f"mode {mode:o}", str(path))


def judge_launchd(res: tuple[int, str] | None) -> dict:
    src = f"launchctl print gui/<uid>/{LABEL}"
    if res is None:
        return line("launchd", UNKNOWN, "launchctl unavailable", src)
    rc, out = res
    if rc != 0:
        return line("launchd", RED, f"not loaded (rc {rc})", src)
    pid = next((ln.split("=", 1)[1].strip() for ln in out.splitlines() if ln.strip().startswith("pid =")), None)
    return line("launchd", OK, f"loaded, pid {pid}" if pid else "loaded, not running", src)


def _open_ro(db: pathlib.Path):
    spec = importlib.util.spec_from_file_location("_ledger_open", pathlib.Path(__file__).resolve().parent / "_ledger_open.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.open_ledger_ro(db)


def judge_ledger(db: pathlib.Path) -> list[dict]:
    con, how = _open_ro(db)
    if con is None:
        return [line("ledger", UNKNOWN, how, str(db)), line("last session", UNKNOWN, "no ledger read", str(db))]
    try:
        row = con.execute("SELECT uuid, actor_id, status, started_at, ended_at, stop_reason"
                          " FROM sessions ORDER BY id DESC LIMIT 1").fetchone()
    except sqlite3.Error as exc:
        con.close()
        return [line("ledger", UNKNOWN, f"unreadable: {exc}", str(db)), line("last session", UNKNOWN, "no ledger read", str(db))]
    con.close()
    try:
        mode = stat.S_IMODE(db.parent.stat().st_mode)
        led = line("ledger", OK if mode == 0o700 else RED, f"readable{', ' + how if how else ''}; dir mode {mode:o}", str(db))
    except OSError as exc:
        led = line("ledger", UNKNOWN, f"dir unreadable ({type(exc).__name__})", str(db.parent))
    if row is None:
        return [led, line("last session", OK, "none yet", str(db))]
    detail = f"{row['started_at']} {row['actor_id']} {row['status']}" + (
        f", ended {row['ended_at']} ({row['stop_reason']})" if row["ended_at"] else "")
    return [led, line("last session", OK, detail, str(db))]


def _launchctl() -> tuple[int, str] | None:
    try:
        p = subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/{LABEL}"], capture_output=True, text=True, timeout=10)
        return p.returncode, p.stdout
    except (OSError, subprocess.TimeoutExpired):
        return None


def collect() -> list[dict]:
    sock = pathlib.Path(os.environ.get("NOS_THALAMUS_SOCKET", HOME / ".nos/thalamus.sock"))
    db = pathlib.Path(os.environ.get("NOS_THALAMUS_LEDGER", HOME / "thalamus/data/ledger.db"))
    return [judge_socket(sock), judge_launchd(_launchctl())] + judge_ledger(db)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    rows = collect()
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        for r in rows:
            print(f"{r['state']:<8} {r['check']:<14} {r['detail']}  [{r['source']}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
