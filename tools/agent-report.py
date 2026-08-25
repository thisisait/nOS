#!/usr/bin/env python3
r"""agent-report.py — print an agent's real report, losslessly.

WHY THIS EXISTS (2026-08-25, upgrade-architect run 8c52551a). The launcher
report said "Review the drafted YAML in the report" and the file it named had
45 lines and zero ```yaml blocks — the 12 drafts lived in the newest
`conductor_report` event's result_json, ~43 KB deep in wing.db. The operator
hand-rolled the extraction and one shell round-trip ate a backslash level:
every `from_regex: "^8\\."` arrived as `"^8\."`, an invalid YAML escape, and
six of ten files failed to parse. The event itself was LOSSLESS — one
json.loads() of result_json yields the drafts byte-exact. The defect was that
no tool owned the read-out, so every reader re-derived it through echo/jq/
copy-paste, each with its own escaping appetite.

This is that tool. It is a READER: opens wing.db read-only, finds the newest
conductor_report for the agent, json-decodes result_json ONCE, and writes the
report field to stdout with no shell re-interpretation. Metadata goes to
stderr so `tools/agent-report.py --agent x > drafts.md` captures a pure
report.

Exit codes: 0 report printed · 1 no matching event · 2 environment error.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--agent", required=True,
                    help="events.source of the conductor_report (e.g. upgrade-architect)")
    ap.add_argument("--db", default=os.environ.get(
        "WING_DB_PATH", os.path.expanduser("~/wing/app/data/wing.db")))
    ap.add_argument("--since", default=None,
                    help="ISO lower bound on events.ts (this run only, not an older one)")
    ap.add_argument("--json", action="store_true", dest="as_json",
                    help="print the whole decoded result_json object, not just .report")
    args = ap.parse_args()

    if not os.path.isfile(args.db):
        print(f"ERROR: wing.db not found at {args.db}", file=sys.stderr)
        return 2

    # mode=ro: this tool must stay a reader whatever it finds.
    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    try:
        sql = ("SELECT id, ts, result_json FROM events "
               "WHERE type='conductor_report' AND source=? ")
        params: list[str] = [args.agent]
        if args.since:
            sql += "AND ts >= ? "
            params.append(args.since)
        sql += "ORDER BY ts DESC LIMIT 1"
        row = con.execute(sql, params).fetchone()
    finally:
        con.close()

    if row is None:
        print(f"ERROR: no conductor_report event from '{args.agent}'"
              + (f" since {args.since}" if args.since else ""), file=sys.stderr)
        return 1

    event_id, ts, raw = row
    try:
        decoded = json.loads(raw) if raw else None
    except (TypeError, json.JSONDecodeError) as exc:
        print(f"ERROR: event {event_id} result_json is not JSON: {exc}", file=sys.stderr)
        return 2

    print(f"event {event_id} at {ts} (source={args.agent})", file=sys.stderr)

    if args.as_json:
        # ensure_ascii=False + no re-escaping: what was stored is what prints.
        sys.stdout.write(json.dumps(decoded, ensure_ascii=False, indent=1))
        sys.stdout.write("\n")
        return 0

    report = decoded.get("report") if isinstance(decoded, dict) else None
    if not isinstance(report, str) or report == "":
        print(f"ERROR: event {event_id} has no .report field — "
              "use --json to see the raw object", file=sys.stderr)
        return 1

    # sys.stdout.write, never a shell echo: echo in zsh/sh interprets
    # backslash escapes and is exactly the round-trip that mangled the
    # 2026-08-25 drafts.
    sys.stdout.write(report)
    if not report.endswith("\n"):
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
