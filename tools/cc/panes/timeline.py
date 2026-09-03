"""Three ledgers on one clock — pulse runs, agent sessions, loop proposals.

Variant E's subject: the estate is loops on a clock, and the question "what ran
in the last hour" crosses three tables that no reader joined. It reads wing.db
directly (read-only) because there is no `--json` tool for the merge.

Honest gap, carried from E and not papered over: `pulse_runs.actor_action_id`
was empty on every row observed 2026-08-29, so a pulse-fired agent session
cannot be joined back to the pulse run that fired it. The column renders as its
own UNKNOWN rather than as a blank that reads like "no lineage".
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ID, LABEL, TITLE = "timeline", "Timeline", "what ran, newest first"
REFRESH = 30
COLUMNS = ["ts", "kind", "name", "status", "took", "lineage"]
DB = Path.home() / "wing/app/data/wing.db"
NO_LINEAGE = "UNKNOWN"

DEMO = {"rows": [
    {"ts": "2026-08-29 12:07", "kind": "agent", "name": "surveyor", "status": "satisfied",
     "took": "2m9s", "lineage": "2ef638ac"},
    {"ts": "2026-08-29 03:00", "kind": "pulse", "name": "gitleaks:nightly-scan",
     "status": "ok", "took": "41s", "lineage": NO_LINEAGE},
]}


def _took(start: str | None, end: str | None) -> str:
    if not start or not end:
        return ""
    try:
        fmt = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))  # noqa: E731
        secs = (fmt(end) - fmt(start)).total_seconds()
    except ValueError:
        return ""
    return f"{secs:.0f}s" if secs < 90 else f"{secs / 60:.0f}m"


def fetch():
    if not DB.is_file():
        return None, f"{DB} is not readable — the timeline is UNKNOWN, not empty"
    # Shared RO open — 2026-08-20 measurement, bit again 2026-09-03
    # (agent-status): bare mode=ro dies when Wing has checkpointed the WAL.
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_ledger_open", Path(__file__).resolve().parents[2] / "_ledger_open.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    conn, how = mod.open_ledger_ro(DB)
    if conn is None:
        return None, f"wing.db: {how}"

    rows = []
    with conn:
        for sql, shape in (
            ("SELECT run_id, job_id AS name, fired_at AS ts, finished_at AS done, "
             " exit_code, actor_action_id AS lineage FROM pulse_runs "
             " ORDER BY fired_at DESC LIMIT 60", "pulse"),
            ("SELECT uuid AS lineage, agent_name AS name, status, outcome_result, "
             " stop_reason, started_at AS ts, ended_at AS done FROM agent_sessions "
             " ORDER BY started_at DESC LIMIT 60", "agent"),
            ("SELECT weakness_id AS name, created_at AS ts, intent_class, "
             " session_uuid AS lineage FROM loop_proposals "
             " ORDER BY created_at DESC LIMIT 60", "proposal"),
        ):
            try:
                found = conn.execute(sql).fetchall()
            except sqlite3.OperationalError:
                continue  # a table this estate has not migrated yet
            for r in found:
                rows.append(_row(dict(r), shape))
    conn.close()
    rows.sort(key=lambda r: r["ts"] or "", reverse=True)
    return {"rows": rows}, None


def _row(r: dict, kind: str) -> dict:
    if kind == "pulse":
        status = ("running" if r["done"] is None
                  else "ok" if r["exit_code"] == 0 else f"fail exit={r['exit_code']}")
    elif kind == "agent":
        status = ("running" if r["status"] in ("pending", "running")
                  else r["outcome_result"] or ("no_verdict" if r["done"] else r["status"]))
    else:
        status = "proposed"
    return {
        "ts": (r["ts"] or "")[:16], "kind": kind, "name": r["name"], "status": status,
        "took": _took(r["ts"], r.get("done")),
        "lineage": (r.get("lineage") or NO_LINEAGE)[:8],
        "_stop_reason": r.get("stop_reason"), "_intent": r.get("intent_class"),
    }


def build_rows(data):
    return data.get("rows", [])


def detail(row, data):
    out = {k: v for k, v in row.items() if not k.startswith("_")}
    if row.get("_stop_reason"):
        out["stop_reason"] = row["_stop_reason"]
    if row.get("_intent"):
        out["intent_class"] = row["_intent"]
    if row.get("lineage") == NO_LINEAGE:
        out["lineage"] = ("UNKNOWN — pulse_runs.actor_action_id is empty on every "
                          "row observed; the join to the fired session does not exist")
    return out
