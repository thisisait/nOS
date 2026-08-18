#!/usr/bin/env python3
"""What is red on this estate right now.

WHY THIS EXISTS. On 2026-08-18 it took six ad-hoc SQL queries to establish
that two nightly jobs had been failing for two days. Nothing was broken about
the detection: both failures notified correctly, on the inbox AND on ntfy, the
first night. Then they went silent — by design, because the repeat-failure rule
that keeps a per-minute job from flooding the inbox also keeps a nightly job
from repeating news that still holds. The inbox meanwhile held **138 unread
rows, 68 of them CRITICAL or HIGH, the oldest 24 days old** — a number I got
wrong by a factor of eight on the first pass, by querying only the last three
days and then quoting the result as the backlog.

So the gap is not detection and it is not delivery. It is that a notification
is an EVENT and red is a STATE, and this estate had no cheap way to ask for the
state. That question has a shape the estate already uses — `estate-status.py`,
`rem-status.py`, `roadmap-status.py` — ask, do not hand-derive. This is the
same shape pointed at operational health.

WHAT IT IS NOT. It does not fix, retry, restart, stamp, or clear anything, and
it never will: half the defects this estate has paid for were a success marker
written by the code that attempted the work. A reader that could also repair
would eventually be asked to certify its own repair. Repair belongs to the
playbook and to the operator.

Every source is a file or a local SQLite read — no network, no Docker, no
daemon. If a source is missing it says so rather than treating absence as
health, because "no data" and "no problem" are the two readings this estate has
most often confused.

Usage:
    tools/red-status.py           # every red, grouped by source
    tools/red-status.py --json    # for a caller
    tools/red-status.py --quiet   # only the count line

Exit 0 always, including when everything is red. Reporting IS its job, and it
can do that; a reader that exited non-zero on bad news would be a gate, and a
gate wired to a calendar goes red on the day upstream publishes, not on a
defect. If you want a hook, read the JSON and decide there.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

REPO = pathlib.Path(__file__).resolve().parents[1]
WING_DB = pathlib.Path.home() / "wing" / "app" / "data" / "wing.db"
SCAN_STATE = REPO / "docs/llm/security/scan-state.json"
BACKUP_STATUS = pathlib.Path.home() / ".nos" / "backup-status.json"

# Backup freshness only. Job lateness is measured against each job's own
# schedule instead — see `overdue_jobs` for why a flat threshold is wrong.
STALE_AFTER = timedelta(days=2)
SCAN_STALE_AFTER = timedelta(days=3)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(raw: str | None) -> datetime | None:
    if not raw:
        return None
    text = raw.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _age(when: datetime | None) -> str:
    if when is None:
        return "unknown age"
    delta = _now() - when
    hours = delta.total_seconds() / 3600
    if hours < 1:
        return f"{int(delta.total_seconds() / 60)} min ago"
    if hours < 48:
        return f"{hours:.0f} h ago"
    return f"{delta.days} d ago"


def _connect() -> sqlite3.Connection | None:
    if not WING_DB.is_file():
        return None
    # read-only: this tool must not be able to write even by accident
    conn = sqlite3.connect(f"file:{WING_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def failing_jobs(conn: sqlite3.Connection) -> list[dict]:
    """Jobs whose MOST RECENT run failed.

    Deliberately last-run rather than any-run-this-week: a job that failed on
    Tuesday and has passed since is history, and history belongs in the
    devlog. What this answers is "is it broken now".
    """
    rows = conn.execute(
        """
        SELECT r.job_id, r.fired_at, r.exit_code, r.duration_ms, r.stdout_tail
          FROM pulse_runs r
          JOIN (SELECT job_id, MAX(fired_at) AS latest
                  FROM pulse_runs GROUP BY job_id) m
            ON r.job_id = m.job_id AND r.fired_at = m.latest
         WHERE r.exit_code IS NOT NULL AND r.exit_code <> 0
         ORDER BY r.fired_at DESC
        """
    ).fetchall()
    out = []
    for row in rows:
        tail = [ln.strip() for ln in (row["stdout_tail"] or "").splitlines() if ln.strip()]
        # Prefer a line that says WHY over the closing banner. The banner is
        # identical every night ("=== FAILED ==="), which is exactly the line a
        # naive "last line" heuristic picks and exactly the line that carries
        # nothing — the vulnerability scan's real reason ("OAuth session
        # expired") sits two lines above it.
        reason = next(
            (ln for ln in reversed(tail)
             if any(word in ln for word in ("ERROR", "Failed", "failed:", "error:"))
             and not ln.rstrip("= ").endswith("FAILED")),
            tail[-1] if tail else "",
        )
        out.append(
            {
                "job": row["job_id"],
                "fired_at": row["fired_at"],
                "age": _age(_parse_iso(row["fired_at"])),
                "exit_code": row["exit_code"],
                "duration_ms": row["duration_ms"],
                "last_line": reason[:160],
            }
        )
    return out


def overdue_jobs(conn: sqlite3.Connection) -> list[dict]:
    """Jobs that were due and did not fire.

    This is the failure mode a red list would otherwise miss entirely: nothing
    failed, because nothing ran.

    MEASURED THE HARD WAY, 2026-08-18. The first version of this asked "has it
    fired in the last two days" and duly reported `conductor:self-test-001` and
    `backup:backup-restore-drill` as red. Both are WEEKLY (`0 4 * * 0`), both
    fired on Sunday exactly as scheduled, and neither was due again for five
    days. A flat threshold cannot tell a stopped job from a job with a longer
    period, and a red list that cries twice a week about healthy jobs is a red
    list nobody finishes reading — which is the very failure this tool exists
    to fix, reintroduced by the tool.

    So the question is asked against the schedule the estate itself computed:
    `next_fire_at` in the past means it was due and did not go. Paused jobs are
    excluded — parked is not red, and the pause carries an operator's reason.
    """
    rows = conn.execute(
        """
        SELECT id, schedule, next_fire_at, last_fired_at, paused_reason
          FROM pulse_jobs
         WHERE paused = 0 AND next_fire_at IS NOT NULL
        """
    ).fetchall()
    now = _now()
    out = []
    for row in rows:
        due = _parse_iso(row["next_fire_at"])
        # a small grace: the daemon fires on a tick, and jobs carry jitter
        if due is None or due > now - timedelta(minutes=90):
            continue
        out.append(
            {
                "job": row["id"],
                "schedule": row["schedule"],
                "due_at": row["next_fire_at"],
                "overdue_by": _age(due).replace(" ago", ""),
                "last_fired": row["last_fired_at"],
            }
        )
    return sorted(out, key=lambda item: item["due_at"])


def unread_inbox(conn: sqlite3.Connection) -> dict:
    rows = conn.execute(
        """
        SELECT severity, COUNT(*) AS n, MIN(created_at) AS oldest
          FROM notifications WHERE wing_inbox_read_at IS NULL
         GROUP BY severity
        """
    ).fetchall()
    by_severity = {row["severity"]: row["n"] for row in rows}
    oldest = min((row["oldest"] for row in rows), default=None)
    loud = sum(by_severity.get(sev, 0) for sev in ("critical", "high"))
    return {
        "total": sum(by_severity.values()),
        "by_severity": by_severity,
        "critical_or_high": loud,
        "oldest": oldest,
        "oldest_age": _age(_parse_iso(oldest)),
    }


def audit_chain(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute(
        """
        SELECT fired_at, exit_code, stdout_tail FROM pulse_runs
         WHERE job_id LIKE '%audit-chain-verify'
         ORDER BY fired_at DESC LIMIT 1
        """
    ).fetchone()
    if row is None:
        return None
    verdict: dict = {}
    for line in reversed((row["stdout_tail"] or "").splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                verdict = json.loads(line)
            except json.JSONDecodeError:
                pass
            break
    return {
        "checked_at": row["fired_at"],
        "age": _age(_parse_iso(row["fired_at"])),
        "exit_code": row["exit_code"],
        "ok": verdict.get("ok"),
        "unsigned": verdict.get("unsigned"),
        "checked": verdict.get("checked"),
    }


def security_scan() -> dict | None:
    if not SCAN_STATE.is_file():
        return None
    data = json.loads(SCAN_STATE.read_text(encoding="utf-8"))
    components = data.get("components") or {}
    if isinstance(components, list):
        components = {c.get("name"): c for c in components}
    failed = sorted(
        name for name, comp in components.items()
        if isinstance(comp, dict) and comp.get("status") == "scan_failed"
    )
    last = _parse_iso(data.get("last_full_scan"))
    return {
        "last_full_scan": data.get("last_full_scan"),
        "age": _age(last),
        "stale": last is None or last < _now() - SCAN_STALE_AFTER,
        "scan_failed": failed,
        "cycle": data.get("scan_cycle"),
    }


def backups() -> dict | None:
    if not BACKUP_STATUS.is_file():
        return None
    data = json.loads(BACKUP_STATUS.read_text(encoding="utf-8"))
    sources = data.get("sources") or []
    if isinstance(sources, dict):
        sources = [{"name": k, **v} for k, v in sources.items() if isinstance(v, dict)]
    failed = [s.get("name") for s in sources if not s.get("success")]
    stamps = [s.get("timestamp") for s in sources if isinstance(s.get("timestamp"), (int, float))]
    when = datetime.fromtimestamp(max(stamps), timezone.utc) if stamps else None
    return {
        "sources": len(sources),
        "failed": failed,
        "last_source_at": when.isoformat() if when else None,
        "age": _age(when),
        "stale": when is None or when < _now() - STALE_AFTER,
    }


def collect() -> dict:
    report: dict = {"generated_at": _now().isoformat(), "sources_read": [], "sources_missing": []}
    conn = _connect()
    if conn is None:
        report["sources_missing"].append(str(WING_DB))
    else:
        report["sources_read"].append(str(WING_DB))
        with conn:
            report["failing_jobs"] = failing_jobs(conn)
            report["overdue_jobs"] = overdue_jobs(conn)
            report["inbox"] = unread_inbox(conn)
            report["audit_chain"] = audit_chain(conn)
        conn.close()

    for label, path, fn in (
        ("security_scan", SCAN_STATE, security_scan),
        ("backups", BACKUP_STATUS, backups),
    ):
        value = fn()
        if value is None:
            report["sources_missing"].append(str(path))
        else:
            report["sources_read"].append(str(path))
            report[label] = value
    return report


def reds(report: dict) -> list[str]:
    """One line per red. The order is the order to act in."""
    out: list[str] = []
    chain = report.get("audit_chain")
    chain_broken = bool(chain and chain.get("ok") is False)
    if chain_broken:
        out.append(
            f"audit chain BROKEN — {chain.get('unsigned')} unsigned of "
            f"{chain.get('checked')} (verified {chain['age']})"
        )
    for job in report.get("failing_jobs", []):
        # the verify job's failure IS the chain verdict above; printing both
        # reads as two problems
        if chain_broken and job["job"].endswith("audit-chain-verify"):
            continue
        out.append(
            f"{job['job']} failing rc={job['exit_code']} ({job['age']}) — {job['last_line']}"
        )
    scan = report.get("security_scan")
    if scan and scan.get("scan_failed"):
        out.append(
            f"security scan: {len(scan['scan_failed'])} component(s) scan_failed "
            f"({', '.join(scan['scan_failed'])}); last full scan {scan['age']}"
        )
    elif scan and scan.get("stale"):
        out.append(f"security scan stale — last full scan {scan['age']}")
    bk = report.get("backups")
    if bk and bk.get("failed"):
        out.append(f"backup sources failed: {', '.join(str(f) for f in bk['failed'])}")
    elif bk and bk.get("stale"):
        out.append(f"backup stale — newest source {bk['age']}")
    for job in report.get("overdue_jobs", []):
        out.append(
            f"{job['job']} was due {job['due_at']} and did not fire "
            f"(overdue {job['overdue_by']}, schedule `{job['schedule']}`)"
        )
    inbox = report.get("inbox") or {}
    if inbox.get("critical_or_high"):
        out.append(
            f"{inbox['critical_or_high']} unread CRITICAL/HIGH in the Wing inbox "
            f"({inbox['total']} unread total, oldest {inbox['oldest_age']})"
        )
    for missing in report.get("sources_missing", []):
        out.append(f"source unreadable, so its state is UNKNOWN not green: {missing}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true", help="emit the full report")
    ap.add_argument("--quiet", action="store_true", help="only the count line")
    args = ap.parse_args()

    report = collect()
    lines = reds(report)
    report["red_count"] = len(lines)
    report["reds"] = lines

    if args.json:
        json.dump(report, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0

    if not lines:
        print("nothing red — every source read and every one green")
        for src in report["sources_read"]:
            print(f"  read {src}")
        return 0

    print(f"{len(lines)} red:")
    if not args.quiet:
        for line in lines:
            print(f"  • {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
