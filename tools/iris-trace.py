#!/usr/bin/env python3
"""What Iris did, turn by turn, from the thalamus ledger: for the OPERATOR to run.

One line per event, newest last: time, session (8 chars), person, kind and detail —
the person's turn, each tool_use with its compact args, each tool_result ok or its
error, Iris's text (first line), approvals asked and decided, and a stop.
Agents never open ledger.db; this reader is the operator's eye on it.

Read-only (sqlite mode=ro, via tools/_ledger_open.py); the ledger path is the one
tools/thalamus-status.py finds (the plist's --data-dir, or NOS_THALAMUS_LEDGER).
Exit 0 always; a ledger it cannot read prints UNKNOWN. Values are cut at 120 chars.

Usage:
    tools/iris-trace.py [--follow] [--session <id>] [--since 10m] [--last 100] [--json]
"""

from __future__ import annotations

import argparse
import functools
import importlib.util
import json
import os
import pathlib
import re
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone

CUT = 120


@functools.cache
def _status():
    spec = importlib.util.spec_from_file_location("_thalamus_status", pathlib.Path(__file__).resolve().parent / "thalamus-status.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _cut(v, n: int = CUT):
    if isinstance(v, str):
        return v if len(v) <= n else v[: n - 1] + "…"
    if isinstance(v, dict):
        return {k: _cut(x, n) for k, x in v.items()}
    if isinstance(v, list):
        return [_cut(x, n) for x in v]
    return v


def _first(text) -> str:
    lines = str(text or "").strip().splitlines()
    return _cut(lines[0] if lines else "")


def describe(kind: str, tool: str, body: dict) -> tuple[str, str] | None:
    """(kind, detail) for one ledger event; None for one the trace leaves out (a branch's copied history)."""
    if kind == "agent_message":
        if body.get("copied"):
            return None
        role, text = body.get("role", "?"), _first(body.get("text"))
        if role == "thalamus":
            return ("stopped" if "stopped" in text.lower() else "thalamus"), text
        return role, text
    if kind == "agent_tool_use":
        args = json.dumps(_cut(body.get("args")), ensure_ascii=False)
        return "tool_use", _cut(f"{tool} {args}", 2 * CUT)
    if kind == "agent_tool_result":
        if "error" in body:
            return "tool_result", f"{tool} error: {_first(body['error'])}"
        return "tool_result", f"{tool} ok"
    if kind == "agent_approval_request":
        return "approval", f"{tool} asked {str(body.get('approval', ''))[:8]}"
    if kind == "agent_approval_decision":
        note = f" ({_first(body['note'])})" if body.get("note") else ""
        return "approval", f"{tool} {body.get('decision', '?')} {str(body.get('approval', ''))[:8]}{note}"
    if kind == "agent_session_end":
        return "session", f"end ({_first(body.get('stop_reason'))})"
    return "session", kind.removeprefix("agent_session_")


def _local(ts: str) -> str:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().strftime("%H:%M:%S")
    except ValueError:
        return ts[:19]


def read(db: pathlib.Path, after: int, session: str | None, since: str | None, last: int):
    """(rows, None) or (None, why). rows are (event id, record) oldest first."""
    con, how = _status()._open_ro(db)
    if con is None:
        return None, how
    where, params = ["e.id > ?"], [after]
    if session:
        where.append("e.run_id LIKE ?")
        params.append(session + "%")
    if since:
        where.append("e.ts >= ?")
        params.append(since)
    sql = (f"SELECT e.id, e.ts, e.run_id, e.type, e.task, e.result_json, e.actor_id FROM events e"
           f" WHERE {' AND '.join(where)} ORDER BY e.id DESC LIMIT ?")
    try:
        got = con.execute(sql, [*params, last]).fetchall()
    except sqlite3.Error as exc:
        return None, f"unreadable: {exc}"
    finally:
        con.close()
    rows = []
    for r in reversed(got):
        try:
            body = json.loads(r["result_json"] or "{}")
        except ValueError:
            body = {}
        tool = (r["task"] or "").partition("/tool:")[2]
        d = describe(r["type"], tool, body if isinstance(body, dict) else {})
        if d:
            rows.append((r["id"], {"time": _local(r["ts"]), "ts": r["ts"], "session": r["run_id"][:8],
                                   "person": r["actor_id"] or "?", "kind": d[0], "tool": tool or None, "detail": d[1]}))
    return rows, None


def _since(s: str | None) -> str | None:
    if not s:
        return None
    m = re.fullmatch(r"(\d+)([smhd])", s)
    if not m:
        raise SystemExit(f"--since takes 30s, 10m, 2h or 1d, not {s!r}")
    secs = int(m[1]) * {"s": 1, "m": 60, "h": 3600, "d": 86400}[m[2]]
    return (datetime.now(timezone.utc) - timedelta(seconds=secs)).strftime("%Y-%m-%dT%H:%M:%S")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--follow", action="store_true", help="poll every second for new events")
    ap.add_argument("--session", help="a session uuid or its prefix")
    ap.add_argument("--since", help="only events this recent: 30s, 10m, 2h, 1d")
    ap.add_argument("--last", type=int, default=100, help="at most this many events at start (default 100)")
    ap.add_argument("--json", action="store_true", help="one JSON object per line")
    a = ap.parse_args()

    st = _status()
    if os.environ.get("NOS_THALAMUS_LEDGER"):
        db, why = pathlib.Path(os.environ["NOS_THALAMUS_LEDGER"]), ""
    else:
        db, why = st.ledger_path(st.PLIST)
    if db is None:
        print(json.dumps({"state": "UNKNOWN", "why": why}) if a.json else f"UNKNOWN  ledger: {why}  [{st.PLIST}]")
        return 0

    after, said_unknown, since, limit = 0, False, _since(a.since), a.last
    try:
        while True:
            rows, why = read(db, after, a.session, since, limit)
            if rows is None:
                if not said_unknown:
                    print(json.dumps({"state": "UNKNOWN", "why": why}) if a.json else f"UNKNOWN  ledger: {why}  [{db}]", flush=True)
                said_unknown = True
            else:
                said_unknown, limit = False, 10_000  # the start window is --last; after it, every new row
                for eid, r in rows:
                    after = eid
                    print(json.dumps(r, ensure_ascii=False) if a.json else
                          f"{r['time']}  {r['session']}  {r['person'][:12]:<12} {r['kind']:<11} {r['detail']}", flush=True)
            if not a.follow:
                return 0
            time.sleep(1)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
