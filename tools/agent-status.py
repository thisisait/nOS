#!/usr/bin/env python3
"""What the agents are doing, and what came of the last ones.

WHY A READER AND NOT A LOG TAIL. The obvious agents pane is `tail -f` on the
runner's output, and it is the wrong shape for the same reason the estate's
healthchecks were: a stopped tail and a quiet agent render identically. Worse,
the thing an operator needs to know about an agent run is not its chatter but
its OUTCOME, and the outcome arrives in a table.

That table is also where this estate's most expensive fact lived unread. From
2026-08-15 to 2026-08-18 the bound loop had FIFTEEN sessions and ZERO
completions; five supervised runs and roughly a million tokens were spent
tuning a prompt before anyone ran the query that says so. This pane is that
query, always on screen.

WHAT IT SHOWS, in the order an operator cares:
  * anything RUNNING right now, with how long it has been running — a run that
    outlives its wall-clock ceiling is a hung process, not a busy one;
  * the last completed runs with their stop reason and token spend;
  * a tally of stop reasons over the recent window, because the SHAPE of the
    failures is the finding — fifteen `ceiling` rows say something a single
    row does not.

A `running` row that will never finish is indistinguishable from one in
progress, so those are called out by age rather than left to look busy.

Usage:
    tools/agent-status.py            # the pane view
    tools/agent-status.py --limit 20
    tools/agent-status.py --json

Exit 0 always. It reports; it never starts, stops or reaps a run.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sqlite3
import sys
from datetime import datetime, timezone

WING_DB = pathlib.Path.home() / "wing" / "app" / "data" / "wing.db"

#: A session open longer than this is almost certainly orphaned: the Runner's
#: own wall-clock ceiling is 3600s, so nothing it drives should outlive it.
HUNG_AFTER_S = 3900


def _connect() -> tuple[sqlite3.Connection | None, str]:
    # 2026-08-20 measurement, bit again 2026-09-03 (agent-status): a bare
    # mode=ro open dies once Wing checkpoints and drops the WAL sidecars.
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_ledger_open", pathlib.Path(__file__).resolve().parent / "_ledger_open.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.open_ledger_ro(WING_DB)


def _age_s(raw: str | None) -> float | None:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - parsed).total_seconds()


def _short(seconds: float | None) -> str:
    if seconds is None:
        return "?"
    if seconds < 90:
        return f"{int(seconds)}s"
    if seconds < 5400:
        return f"{int(seconds / 60)}m"
    if seconds < 172800:
        return f"{seconds / 3600:.0f}h"
    return f"{seconds / 86400:.0f}d"


def collect(limit: int) -> dict:
    conn, how = _connect()
    if conn is None:
        return {"error": f"wing.db UNKNOWN — {how}", "running": [], "recent": []}

    with conn:
        rows = [dict(r) for r in conn.execute(
            """
            SELECT uuid, agent_name, status, stop_reason, outcome_result,
                   model_uri, trigger, started_at, ended_at,
                   tokens_input, tokens_output
              FROM agent_sessions
             ORDER BY started_at DESC
             LIMIT ?
            """,
            (max(limit, 30),),
        )]
        tally = [dict(r) for r in conn.execute(
            """
            SELECT COALESCE(stop_reason, status) AS how, COUNT(*) AS n
              FROM agent_sessions
             WHERE started_at > datetime('now', '-14 days')
             GROUP BY how ORDER BY n DESC
            """
        )]
    conn.close()

    running, recent = [], []
    for row in rows:
        age = _age_s(row["started_at"])
        item = {
            "uuid": row["uuid"][:8],
            "agent": row["agent_name"],
            "status": row["status"],
            "stop_reason": row["stop_reason"],
            "outcome": row["outcome_result"],
            # `cli:` and `claude-cli` are the CLI path; anything else is the
            # in-process bound loop. The distinction is the whole story of
            # which runner has ever finished anything.
            "bound": not str(row["model_uri"] or "").startswith(("cli:", "claude-cli")),
            "trigger": row["trigger"],
            "age_s": age,
            "age": _short(age),
            "tokens_in": row["tokens_input"] or 0,
            "tokens_out": row["tokens_output"] or 0,
        }
        if row["status"] == "running":
            item["hung"] = age is not None and age > HUNG_AFTER_S
            running.append(item)
        else:
            recent.append(item)

    return {
        "ledger": str(WING_DB),
        "running": running,
        "recent": recent[:limit],
        "tally_14d": tally,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    report = collect(args.limit)
    if args.json:
        json.dump(report, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0

    if report.get("error"):
        print(report["error"])
        return 0

    if report["running"]:
        print("RUNNING")
        for r in report["running"]:
            flag = "  ← OPEN LONGER THAN THE WALL CLOCK; likely orphaned" if r.get("hung") else ""
            print(f"  {r['agent']:<16} {r['uuid']}  {r['age']:>5}  "
                  f"{'bound' if r['bound'] else 'cli':<5}{flag}")
    else:
        print("RUNNING  — none")

    print("\nLAST RUNS")
    for r in report["recent"]:
        how = r["stop_reason"] or r["status"]
        outcome = f"/{r['outcome']}" if r["outcome"] else ""
        print(f"  {r['agent']:<16} {r['age']:>5} ago  {'bound' if r['bound'] else 'cli':<5} "
              f"{how}{outcome:<18} {r['tokens_in']:>7}in {r['tokens_out']:>6}out")

    if report["tally_14d"]:
        print("\nHOW RUNS ENDED (14d)")
        print("  " + " · ".join(f"{t['how']} {t['n']}" for t in report["tally_14d"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
