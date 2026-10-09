#!/usr/bin/env python3
"""What the last estate e2e run (tests/e2e/estate) said, read back from its record.

The suite's conftest appends one JSON line per probe to ~/.nos/e2e/results.jsonl
(NOS_E2E_RESULTS overrides the path). This reader summarises the LAST run_id in
that file: counts per outcome, the failing nodeids, how old it is. Red: any
failure, or a last run older than 7 days. No file = UNKNOWN, never green.

Reads only. Exit 0 always.

Usage:
    tools/e2e-status.py            # table
    tools/e2e-status.py --json
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

STALE_DAYS = 7


def _path() -> pathlib.Path:
    return pathlib.Path(os.environ.get("NOS_E2E_RESULTS")
                        or pathlib.Path.home() / ".nos" / "e2e" / "results.jsonl")


def collect(now: datetime | None = None) -> dict:
    now = now or datetime.now(tz=timezone.utc)
    path = _path()
    report: dict = {"sources_missing": [], "path": str(path)}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        report["sources_missing"].append(f"{path} ({exc.strerror or exc})")
        return report
    rows = []
    for line in lines:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get("type") == "e2e_result" and r.get("run_id"):
            rows.append(r)
    if not rows:
        report["sources_missing"].append(f"{path} (no e2e_result rows)")
        return report
    run_id = rows[-1]["run_id"]
    last = [r for r in rows if r["run_id"] == run_id]
    ts = max(r.get("ts") or "" for r in last)
    try:
        when = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        when = None
    report.update({
        "run_id": run_id, "ts": ts, "total": len(last),
        "counts": dict(Counter(r.get("outcome", "?") for r in last)),
        "failed": [r["nodeid"] for r in last if r.get("outcome") == "failed"],
        "age_days": (now - when).days if when else None,
        "stale": when is None or when < now - timedelta(days=STALE_DAYS),
    })
    return report


def summary(report: dict) -> list[str]:
    """One phrase per red — red-status joins them into its line."""
    out = []
    if report.get("failed"):
        out.append(f"last e2e run {report['run_id']} had {len(report['failed'])} failure(s): "
                   + ", ".join(report["failed"][:5]) + (" …" if len(report["failed"]) > 5 else ""))
    if report.get("run_id") and report.get("stale"):
        out.append(f"last e2e run {report['run_id']} is older than {STALE_DAYS} days ({report['ts']})")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    report = collect()
    if args.json:
        json.dump(report, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0
    if report["sources_missing"]:
        for m in report["sources_missing"]:
            print(f"e2e: UNKNOWN — {m} unreadable, not green")
        return 0
    counts = ", ".join(f"{n} {k}" for k, n in sorted(report["counts"].items()))
    print(f"e2e: last run {report['run_id']} at {report['ts']} ({report['age_days']}d ago): "
          f"{report['total']} probes — {counts}")
    for n in report["failed"]:
        print(f"  FAIL  {n}")
    for line in summary(report):
        print(f"  red   {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
