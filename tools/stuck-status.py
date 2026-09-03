#!/usr/bin/env python3
"""What has STOPPED MOVING — which is a different question from what is broken.

`tools/red-status.py` answers "what is failing". Everything it lists is loud:
a job exited non-zero, a chain refuses to verify, a scan died. This answers the
quieter one — what was started, is not finished, and has not moved. Nothing here
is failing. That is exactly why it accumulates: a stalled item emits no event, so
no notification exists to ignore, and the only way to see it is to ask.

The estate has form here. Four hidden-fee entries were found on 2026-08-18 to
have been PAID long before, with nobody walking back to the record; five weakness
detectors have run for weeks and produced not one proposal; the security queue
carries rows first seen months ago. None of that fails anything. All of it is
work that stopped.

WHAT COUNTS AS STUCK, and why each is measured the way it is:

  queue      a pending remediation, aged from its own `found_at`. Severity
             decides the threshold — a CRITICAL sitting for a week is a
             different fact from a LOW sitting for a month.
  fees       an OPEN hidden fee, aged from the git history of its own file,
             because the entry's prose date is a claim and the commit is not.
  detectors  a weakness source that reports and has never once led to a
             proposal. "Which detectors earn their run" was unanswerable until
             `loop-status.py`; a source that never proposes looks identical to
             one that always does, from inside.
  agents     an agent with sessions and no completion. Fifteen of those went
             unread for three days and cost roughly a million tokens.
  parked     a paused Pulse job. Parked is NOT stuck — the pause carries an
             operator's reason — so these are listed without alarm, as the
             answer to "what did we decide not to run, and why".

Usage:
    tools/stuck-status.py            # the board
    tools/stuck-status.py --plain    # no colour or box drawing
    tools/stuck-status.py --json

Exit 0 always. Nothing here is a defect a commit introduced.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone

REPO = pathlib.Path(__file__).resolve().parents[1]
WING_DB = pathlib.Path.home() / "wing" / "app" / "data" / "wing.db"
QUEUE = REPO / "docs/llm/security/remediation-queue.json"
FEES = REPO / "docs/hidden_fees"

#: Days after which a pending row stops being "in progress" and starts being
#: "stalled". Scaled by severity: the estate's own disposition language treats a
#: CRITICAL as something to act on now and a LOW as something to batch.
STALE_DAYS = {"CRITICAL": 7, "HIGH": 21, "MEDIUM": 60, "LOW": 120}

ANSI = {
    "dim": "\033[2m", "bold": "\033[1m", "reset": "\033[0m",
    "red": "\033[31m", "yellow": "\033[33m", "green": "\033[32m",
    "cyan": "\033[36m", "grey": "\033[90m",
}


def _c(text: str, *styles: str, plain: bool = False) -> str:
    if plain or not sys.stdout.isatty():
        return text
    return "".join(ANSI[s] for s in styles) + text + ANSI["reset"]


def _age_days(raw: str | None) -> float | None:
    if not raw:
        return None
    text = str(raw).strip().replace("Z", "+00:00")
    for candidate in (text, text[:10]):
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - parsed).total_seconds() / 86400
    return None


def queue_rows() -> list[dict]:
    if not QUEUE.is_file():
        return []
    data = json.loads(QUEUE.read_text(encoding="utf-8"))
    rows = data.get("items") if isinstance(data, dict) else data
    out = []
    for row in rows or []:
        if row.get("status") != "pending":
            continue
        sev = str(row.get("severity", "LOW")).upper()
        age = _age_days(row.get("found_at"))
        out.append({
            "id": row.get("id"),
            "component": row.get("component"),
            "severity": sev,
            "age_days": age,
            "stale": age is not None and age > STALE_DAYS.get(sev, 120),
        })
    order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    return sorted(out, key=lambda r: (order.get(r["severity"], 9), -(r["age_days"] or 0)))


def fee_rows() -> list[dict]:
    """Open fees, aged from git rather than from the prose.

    The entry's own "Found 2026-08-07" line is a CLAIM by the author; the first
    commit that carried the file is a fact. Where they disagree the commit wins,
    and that disagreement is itself worth seeing.
    """
    out = []
    for path in sorted(FEES.glob("[0-9][0-9]-*.md")):
        head = "\n".join(path.read_text(encoding="utf-8").splitlines()[:12])
        status = re.search(r"\*\*Status:?\*{0,2}\s*([^\n.]+)", head)
        label = (status.group(1) if status else "").strip()
        closed = bool(re.search(r"\bCLOSED\b", head, re.I)) or label.lower().startswith("closed")
        if closed:
            continue
        first = subprocess.run(
            ["git", "log", "--reverse", "--format=%aI", "--", str(path.relative_to(REPO))],
            cwd=REPO, capture_output=True, text=True,
        ).stdout.split("\n")[0].strip()
        out.append({
            "fee": path.name[:2],
            "slug": path.stem[3:],
            "status": label[:48] or "open",
            "age_days": _age_days(first),
        })
    return sorted(out, key=lambda r: -(r["age_days"] or 0))


def loop_and_agents() -> dict:
    # 2026-08-20 measurement, bit again 2026-09-03 (agent-status): a bare
    # mode=ro open dies once Wing checkpoints and drops the WAL sidecars.
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_ledger_open", REPO / "tools" / "_ledger_open.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    conn, how = mod.open_ledger_ro(WING_DB)
    if conn is None:
        return {"ledger_unknown": how, "silent_detectors": [],
                "agents_mostly_cut_off": [], "parked": []}
    with conn:
        proposed = {
            str(r["w"]).split(":", 1)[0]
            for r in conn.execute("SELECT DISTINCT weakness_id AS w FROM loop_proposals")
        }
        # ENDED vs CUT OFF, which is the distinction that matters and the one
        # a first draft of this tool got wrong. `outcome_failed` looks like a
        # failure and IS a completion: the ceremony ran, produced a report, and
        # a grader judged it. `ceiling` and `error` are the opposite — the run
        # was stopped mid-work and produced nothing to judge. Counting
        # outcome_failed as "never completed" told the operator that surveyor
        # had produced nothing on the very day it first produced a report.
        agents = [dict(r) for r in conn.execute(
            """
            SELECT agent_name,
                   COUNT(*) AS runs,
                   SUM(CASE WHEN stop_reason IN ('run_end','outcome_satisfied',
                                                 'outcome_failed','outcome_needs_revision',
                                                 'call_cap_synthesis','ceiling_synthesis')
                            THEN 1 ELSE 0 END) AS ended,
                   SUM(CASE WHEN stop_reason IN ('ceiling','error') OR stop_reason IS NULL
                            THEN 1 ELSE 0 END) AS cut_off,
                   MAX(started_at) AS last
              FROM agent_sessions GROUP BY agent_name
            """
        )]
        parked = [dict(r) for r in conn.execute(
            "SELECT id, paused_reason FROM pulse_jobs WHERE paused = 1 ORDER BY id"
        )]
    conn.close()

    # Sources the reader KNOWS about. Kept as a literal list rather than derived
    # from Bone: this tool must answer on a host where Bone cannot import, and
    # naming a source that reports nothing is better than omitting it silently.
    known = ["rem", "fee", "scan", "git", "corpus", "alert", "pulse"]
    return {
        "silent_detectors": [s for s in known if s not in proposed],
        "agents_mostly_cut_off": sorted(
            (
                {"agent": a["agent_name"], "runs": a["runs"],
                 "ended": a["ended"] or 0, "cut_off": a["cut_off"] or 0,
                 "last": a["last"], "age_days": _age_days(a["last"])}
                for a in agents
                if (a["cut_off"] or 0) > (a["ended"] or 0)
            ),
            key=lambda a: -a["cut_off"],
        ),
        "parked": parked,
    }


def collect() -> dict:
    report = {"queue": queue_rows(), "fees": fee_rows()}
    report.update(loop_and_agents())
    report["stuck_count"] = (
        sum(1 for r in report["queue"] if r["stale"])
        + len(report["fees"])
        + len(report["silent_detectors"])
        + len(report["agents_mostly_cut_off"])
    )
    return report


def render(report: dict, plain: bool) -> None:
    def head(title: str, note: str = "") -> None:
        bar = "─" * max(4, 58 - len(title))
        print(f"\n{_c('┤ ' + title + ' ├', 'bold', 'cyan', plain=plain)}{_c(bar, 'grey', plain=plain)}")
        if note:
            print(_c("  " + note, "grey", plain=plain))

    stale = [r for r in report["queue"] if r["stale"]]
    head("security queue", f"{len(stale)} of {len(report['queue'])} pending rows past their severity's window")
    for row in stale[:8]:
        sev = row["severity"]
        colour = "red" if sev in ("CRITICAL", "HIGH") else "yellow"
        age = f"{row['age_days']:.0f}d" if row["age_days"] is not None else "?"
        print(f"  {_c(sev.ljust(8), colour, plain=plain)} {str(row['id']):<9} "
              f"{str(row['component']):<14} {_c(age, 'dim', plain=plain)}")
    if len(stale) > 8:
        print(_c(f"  … and {len(stale) - 8} more", "grey", plain=plain))

    head("hidden fees", f"{len(report['fees'])} open, oldest first")
    for row in report["fees"][:8]:
        age = f"{row['age_days']:.0f}d" if row["age_days"] else "?"
        print(f"  {_c(row['fee'], 'bold', plain=plain)}  {row['slug'][:34]:<34} "
              f"{_c(age.rjust(5), 'dim', plain=plain)}  "
              f"{_c(row['status'][:36], 'grey', plain=plain)}")

    head("detectors that have never proposed",
         "reporting weaknesses that never became a proposal — is the detector earning its run?")
    if report.get("ledger_unknown"):
        print("  " + _c(f"? wing.db UNKNOWN — {report['ledger_unknown']}",
                        "yellow", plain=plain))
    elif report["silent_detectors"]:
        print("  " + _c(" · ".join(report["silent_detectors"]), "yellow", plain=plain))
    else:
        print("  " + _c("none — every source has led somewhere", "green", plain=plain))

    head("agents whose runs get cut off more often than they end",
         "cut off = ceiling or error, nothing to judge · ended = a grader saw a report")
    if report.get("ledger_unknown"):
        print("  " + _c("? UNKNOWN — wing.db unreadable", "yellow", plain=plain))
    elif report["agents_mostly_cut_off"]:
        for a in report["agents_mostly_cut_off"]:
            age = f"{a['age_days']:.0f}d ago" if a["age_days"] else "never"
            print(f"  {_c(a['agent'].ljust(16), 'yellow', plain=plain)} "
                  f"{a['cut_off']:>2} cut off / {a['ended']:>2} ended, last {age}")
    else:
        print("  " + _c("none — every agent ends more runs than it loses", "green", plain=plain))

    head("parked on purpose", "a pause carries a reason; this is not a backlog")
    for p in report["parked"][:6]:
        print(f"  {_c(p['id'].ljust(34), 'dim', plain=plain)} "
              f"{_c((p['paused_reason'] or '')[:40], 'grey', plain=plain)}")
    if len(report["parked"]) > 6:
        print(_c(f"  … and {len(report['parked']) - 6} more", "grey", plain=plain))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--plain", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    report = collect()
    if args.json:
        json.dump(report, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0
    render(report, args.plain)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
