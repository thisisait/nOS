#!/usr/bin/env python3
"""Measure the nightly chain's temporal margins, and restamp the declared edges.

WHY THIS TOOL EXISTS
--------------------
The nightly knowledge chain (keap-consolidate → cortex-fs-sync →
keap-embed-sync → keap-features-sync → keap-lint → cortex-corpus-diff) is
ordered by nothing but cron minutes plus per-job jitter. The manifests now
declare that ordering as `depends_on` edges with `kind: temporal`, and the
soundness gate (tests/anatomy/test_anatomy_graph_is_sound.py) refuses a
temporal edge whose recorded `schedules` no longer match the two jobs' cron
expressions. Changing a schedule therefore makes the edit INCOMPLETE until
this tool re-measures the margin and restamps the edge — which is the point:
the 2026-08-06 survey (docs/archive/nos-anatomy-graph.md §1.4) measured that
every chain edge but one is already *permitted* to invert by its own declared
budgets, and on 2026-07-27 the chain actually scrambled and nothing noticed.

WHAT A MARGIN IS
----------------
For a temporal edge upstream → downstream, per calendar night:

    margin = downstream.fired_at − upstream.finished_at   (minutes)

computed over the wing.db `pulse_runs` table, night runs only (a run counts
as a night run when it fired within NIGHT_WINDOW_MIN minutes after its job's
cron minute — the 2026-07-27 11:34 refire must not pollute the statistic).
`margin_min` stamped into the manifest is the MINIMUM over the window, i.e.
the worst night actually observed. The denominator (nights paired) is always
printed; a margin over 2 nights is a different claim than one over 10.

USAGE
-----
    tools/anatomy-measure-margins.py                # measure declared edges, print
    tools/anatomy-measure-margins.py --stamp        # also rewrite margin_min/measured
    tools/anatomy-measure-margins.py --check        # exit 1 if any stamp is stale
    tools/anatomy-measure-margins.py --pair keap:keap-consolidate cortex:cortex-fs-sync
    tools/anatomy-measure-margins.py --db PATH --days N

This tool touches ONLY `margin_min:` and `measured:` lines inside temporal
`depends_on` entries. It never adds or removes an edge — authoring an edge is
a human/agent act reviewed with the schedule it constrains.

Exit: 0 ok, 1 stale stamps (--check) or no nights paired for a declared edge,
2 usage/db error.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sqlite3
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]

#: Same walk as tests/anatomy/test_every_job_declares_what_it_is.py — both
#: sources, because a temporal edge in an agent profile must not be invisible.
SOURCES = ("files/anatomy/plugins/*/plugin.yml", "files/anatomy/agents/*.yml")

DEFAULT_DB = Path.home() / "wing" / "app" / "data" / "wing.db"

#: A run is a "night run" of its job when it fired within this many minutes
#: AFTER the cron minute. Covers declared jitter (max 10 on the chain) plus
#: the 30 s tick plus slow dispatch; excludes same-day refires hours later.
NIGHT_WINDOW_MIN = 45


def _owner(doc: dict, path: Path) -> str:
    return re.sub(r"-base$", "", str(doc.get("name") or doc.get("agent_id") or path.stem))


def walk_jobs() -> dict[str, dict]:
    """pulse job id ('owner:job') → {schedule, path, job block}."""
    out: dict[str, dict] = {}
    for pattern in SOURCES:
        for path in sorted(REPO.glob(pattern)):
            try:
                doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError:
                continue
            if not isinstance(doc, dict):
                continue
            for job in (doc.get("pulse") or {}).get("jobs") or []:
                if isinstance(job, dict) and job.get("name"):
                    jid = f"{_owner(doc, path)}:{job['name']}"
                    out[jid] = {"schedule": job.get("schedule"), "path": path, "job": job}
    return out


def declared_temporal_edges(jobs: dict[str, dict]) -> list[dict]:
    """Every `kind: temporal` depends_on entry, with its consumer's identity."""
    edges = []
    for jid, info in jobs.items():
        for dep in info["job"].get("depends_on") or []:
            if isinstance(dep, dict) and dep.get("kind") == "temporal":
                # The field is `upstream:`, never `on:` — YAML 1.1 parses a
                # bare `on` key as boolean True (see anatomy-graph-gen.py).
                edges.append({
                    "upstream": str(dep.get("upstream", "")).removeprefix("pulse:"),
                    "downstream": jid,
                    "declared": dep,
                    "path": info["path"],
                })
    return edges


def _cron_minute_of_day(schedule: str) -> int | None:
    """'30 4 * * *' → 270. None for anything not a fixed daily minute."""
    parts = (schedule or "").split()
    if len(parts) != 5 or not parts[0].isdigit() or not parts[1].isdigit():
        return None
    return int(parts[1]) * 60 + int(parts[0])


def _night_runs(cur, job_id: str, minute_of_day: int, days: int) -> dict[str, tuple[str, str]]:
    """date → (fired_at, finished_at) for runs firing inside the night window."""
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).strftime("%Y-%m-%d")
    rows = cur.execute(
        "SELECT fired_at, finished_at FROM pulse_runs "
        "WHERE job_id = ? AND fired_at >= ? AND finished_at IS NOT NULL "
        "ORDER BY fired_at",
        (job_id, since),
    ).fetchall()
    out: dict[str, tuple[str, str]] = {}
    for fired, finished in rows:
        try:
            t = dt.datetime.fromisoformat(fired)
        except ValueError:
            continue
        offset = (t.hour * 60 + t.minute) - minute_of_day
        if 0 <= offset <= NIGHT_WINDOW_MIN and t.date().isoformat() not in out:
            out[t.date().isoformat()] = (fired, finished)
    return out


def measure(cur, up_id: str, up_sched: str, down_id: str, down_sched: str,
            days: int) -> dict:
    """min/avg margin (minutes) + the denominator, or an honest refusal."""
    up_min = _cron_minute_of_day(up_sched)
    down_min = _cron_minute_of_day(down_sched)
    if up_min is None or down_min is None:
        return {"nights": 0, "note": "schedule is not a fixed daily minute"}
    ups = _night_runs(cur, up_id, up_min, days)
    downs = _night_runs(cur, down_id, down_min, days)
    margins = []
    for date, (_, up_finished) in ups.items():
        if date in downs:
            down_fired = downs[date][0]
            m = (dt.datetime.fromisoformat(down_fired)
                 - dt.datetime.fromisoformat(up_finished)).total_seconds() / 60.0
            margins.append(m)
    if not margins:
        return {"nights": 0, "note": "no nights with both runs in the window"}
    return {
        "nights": len(margins),
        "margin_min": round(min(margins), 1),
        "margin_avg": round(sum(margins) / len(margins), 1),
    }


# ── stamping — the ONLY writes this tool performs ─────────────────────────


def _stamp_file(path: Path, upstream_on: str, downstream_job: str,
                margin_min: float, today: str) -> bool:
    """Rewrite margin_min/measured inside ONE temporal edge, line-anchored.

    The anchor is the `- upstream:` line carrying the upstream id inside the
    downstream job's block, followed (within the same entry) by
    `kind: temporal`. YAML round-tripping would strip the manifests' comments,
    which carry the estate's institutional memory — so this is a surgical
    line edit instead, and it refuses (returns False) rather than guessing
    when the shape is not what it expects.
    """
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    in_job = False
    entry_start = None
    entry_is_target = False
    changed = False
    for i, line in enumerate(lines):
        if re.match(rf"\s*-\s*name:\s*{re.escape(downstream_job)}\s*$", line):
            in_job = True
            continue
        if in_job and re.match(r"\s*-\s*name:\s*\S+", line):
            in_job = False  # next job began
        if not in_job:
            continue
        m = re.match(r"(\s*)-\s*upstream:\s*[\"']?([^\"'\s]+)[\"']?", line)
        if m:
            entry_start = i
            entry_is_target = m.group(2) == upstream_on
            continue
        if entry_start is None or not entry_is_target:
            continue
        km = re.match(r"(\s*)kind:\s*(\S+)", line)
        if km and km.group(2) != "temporal":
            entry_is_target = False
            continue
        mm = re.match(r"(\s*)margin_min:\s*\S+(\s*#.*)?", line)
        if mm:
            lines[i] = f"{mm.group(1)}margin_min: {margin_min}{mm.group(2) or ''}\n"
            changed = True
            continue
        dm = re.match(r"(\s*)measured:\s*\S+(\s*#.*)?", line)
        if dm:
            # QUOTED on purpose: a bare ISO date is a datetime.date to PyYAML,
            # and the pulse-catalog harvest json.dumps() the whole job block —
            # an unquoted stamp here crashes discover-pulse-catalog.py.
            lines[i] = f'{dm.group(1)}measured: "{today}"{dm.group(2) or ""}\n'
            changed = True
    if changed:
        path.write_text("".join(lines), encoding="utf-8")
    return changed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--days", type=int, default=10)
    ap.add_argument("--stamp", action="store_true",
                    help="rewrite margin_min/measured on declared temporal edges")
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if a declared margin_min differs from measurement")
    ap.add_argument("--pair", nargs=2, metavar=("UP", "DOWN"),
                    help="ad-hoc measurement of two pulse job ids (authoring aid)")
    args = ap.parse_args()

    if not args.db.exists():
        print(f"error: wing.db not found at {args.db}", file=sys.stderr)
        return 2
    cur = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True).cursor()
    jobs = walk_jobs()
    today = dt.date.today().isoformat()

    if args.pair:
        up, down = args.pair
        for jid in (up, down):
            if jid not in jobs:
                print(f"error: unknown pulse job id {jid!r}", file=sys.stderr)
                return 2
        r = measure(cur, up, jobs[up]["schedule"], down, jobs[down]["schedule"], args.days)
        r |= {"upstream": up, "downstream": down,
              "schedules": [jobs[up]["schedule"], jobs[down]["schedule"]],
              "window_days": args.days}
        print(json.dumps(r, indent=2))
        return 0

    edges = declared_temporal_edges(jobs)
    if not edges:
        print("no temporal depends_on edges declared in the manifests")
        return 0

    stale = 0
    unpaired = 0
    for e in edges:
        up, down = e["upstream"], e["downstream"]
        if up not in jobs:
            print(f"SKIP {up} -> {down}: upstream not in the catalog (the soundness gate owns this)")
            continue
        r = measure(cur, up, jobs[up]["schedule"], down, jobs[down]["schedule"], args.days)
        declared = e["declared"].get("margin_min")
        if r["nights"] == 0:
            print(f"UNPAIRED {up} -> {down}: {r['note']} (declared margin_min={declared})")
            unpaired += 1
            continue
        line = (f"{up} -> {down}: min {r['margin_min']} avg {r['margin_avg']} min "
                f"over {r['nights']}/{args.days} nights (declared {declared})")
        if declared != r["margin_min"]:
            stale += 1
            line += "  [STALE]"
            if args.stamp:
                ok = _stamp_file(e["path"], f"pulse:{up}", down.split(":", 1)[1],
                                 r["margin_min"], today)
                line += "  [stamped]" if ok else "  [STAMP FAILED — shape not recognised]"
        print(line)

    if args.check and stale:
        print(f"\n{stale} temporal edge(s) carry a margin the estate no longer measures",
              file=sys.stderr)
        return 1
    return 1 if unpaired else 0


if __name__ == "__main__":
    sys.exit(main())
