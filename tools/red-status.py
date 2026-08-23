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
#: Read to re-decide a `security-drift` notification's own claim — see
#: `_still_holds`. A file, like every other source here.
REMEDIATION_QUEUE = REPO / "docs/llm/security/remediation-queue.json"
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


#: Filled by `_connect` when the ledger could only be read as a snapshot, so
#: `collect()` can say which kind of read it got instead of implying the normal
#: one. Empty string = the normal read-only path.
LEDGER_READ_NOTE = ""


def _connect() -> sqlite3.Connection | None:
    """Read-only, and None rather than an exception when that is impossible.

    Still `mode=ro` first — this tool must not be able to write even by
    accident. What changed on 2026-08-20 is the failure path: `wing.db` is WAL,
    a WAL reader needs the `-shm` index, a read-only connection may not create
    it, and Wing does not hold the database between requests. So after every
    converge this raised `unable to open database file` as an uncaught
    traceback — in the one tool whose docstring promises that a missing source
    "says so rather than treating absence as health".
    """
    global LEDGER_READ_NOTE
    import importlib.util  # noqa: PLC0415 — sibling helper, not a package

    spec = importlib.util.spec_from_file_location(
        "_ledger_open", REPO / "tools" / "_ledger_open.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    conn, how = mod.open_ledger_ro(WING_DB)
    LEDGER_READ_NOTE = how
    return conn


def failing_jobs(conn: sqlite3.Connection) -> list[dict]:
    """Jobs whose MOST RECENT run failed.

    Deliberately last-run rather than any-run-this-week: a job that failed on
    Tuesday and has passed since is history, and history belongs in the
    devlog. What this answers is "is it broken now".
    """
    # A NON-ZERO EXIT IS NOT ALWAYS A FAILURE. A job may DECLARE which codes
    # mean "I found something" — `pulse_jobs.findings_exit_codes`, honoured by
    # the plugin manifests and by `bin/reconcile-inbox.php`. This reader did not
    # know the column existed, so on 2026-08-20 it called
    # `discovery:contradiction-scan` failing for exiting 1 after doing exactly
    # its job ("filed 1 new roadmap row(s)"). Two readers disagreeing about one
    # fact is worse than either being wrong alone, and a reader that cries wolf
    # is one the operator learns to discount — which is the whole thing this
    # file was written to prevent.
    rows = conn.execute(
        """
        SELECT r.job_id, r.fired_at, r.exit_code, r.duration_ms, r.stdout_tail,
               j.findings_exit_codes
          FROM pulse_runs r
          JOIN (SELECT job_id, MAX(fired_at) AS latest
                  FROM pulse_runs GROUP BY job_id) m
            ON r.job_id = m.job_id AND r.fired_at = m.latest
          LEFT JOIN pulse_jobs j ON j.id = r.job_id
         WHERE r.exit_code IS NOT NULL AND r.exit_code <> 0
         ORDER BY r.fired_at DESC
        """
    ).fetchall()
    out = []
    for row in rows:
        # Declared findings code → the job worked. Unparseable declaration is
        # NOT read as "no codes declared": that would silently restore the old
        # behaviour, so it falls through to reporting the job, which is the
        # safe direction for a reader whose job is bad news.
        declared = row["findings_exit_codes"]
        if declared:
            try:
                if int(row["exit_code"]) in {int(c) for c in json.loads(declared)}:
                    continue
            except (TypeError, ValueError):
                pass
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


def _queue_pending() -> dict[str, int] | None:
    """Pending counts by severity, from the queue file. None if unreadable."""
    try:
        data = json.loads(REMEDIATION_QUEUE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    counts: dict[str, int] = {}
    for item in data.get("items", []):
        if item.get("status") == "pending":
            sev = str(item.get("severity", "")).lower()
            counts[sev] = counts.get(sev, 0) + 1
    return counts


def _still_holds(row: sqlite3.Row) -> bool | None:
    """Does this notification's own claim still hold?

    A notification is an EVENT and red is a STATE — the sentence this whole
    file exists for. The inbox is where that distinction was never applied:
    every one of the four unread CRITICAL security-drift rows was TRUE when
    sent (on 2026-08-22 there really were 11 pending HIGH; they were closed
    that afternoon) and every one of them is now false. Counting them as red
    makes this reader do the thing it was built to stop — generate a red from
    a stale event.

    Re-evaluation is only possible where the emitter recorded a MEASURABLE
    claim. `security-drift` records `{"pending_critical": "1", ...}`, which is
    a count of rows in a file this reader may open. Where the claim is prose,
    or the source is a daemon this reader must not touch, the honest answer is
    None — unknown, never "cleared".
    """
    origin = (row["origin_plugin"] or row["origin_agent"] or "").strip()
    try:
        meta = json.loads(row["metadata_json"] or "{}")
    except ValueError:
        return None
    if not isinstance(meta, dict) or not meta:
        return None

    if origin == "security-drift":
        now = _queue_pending()
        if now is None:
            return None
        for key, sev in (("pending_critical", "critical"), ("pending_high", "high")):
            try:
                claimed = int(meta[key])
            except (KeyError, TypeError, ValueError):
                continue
            # Still red if the estate has AT LEAST as many as were reported.
            # Fewer means the specific alarm was answered; more is a new
            # problem that will have raised its own notification.
            if claimed and now.get(sev, 0) >= claimed:
                return True
        return False
    return None


def _notifications_have_supersede(conn: sqlite3.Connection) -> bool:
    """The supersede columns arrive via init-db.php's ALTER sweep, which runs
    on a converge. This reader must work on a host that has not had one yet —
    and must not silently report a DIFFERENT number there without saying so.

    The PRAGMA is spelled as a LITERAL, and the two queries below are written
    out twice rather than built from a fragment, because
    `test_the_red_reader_only_reads.py` requires every executed statement to be
    a visible constant. That rule cost this duplication and is worth it: it is
    what lets a gate prove the reader cannot write."""
    try:
        return any(r[1] == "superseded_at"
                   for r in conn.execute("PRAGMA table_info(notifications)"))
    except sqlite3.Error:
        return False


def unread_inbox(conn: sqlite3.Connection) -> dict:
    # A superseded row is not unread WORK: its successor already said the newer
    # version of the same thing. Excluding it here is the whole point of the
    # column — 60 of 76 unread rows on 2026-08-23 were repeating classes.
    retired = _notifications_have_supersede(conn)
    if retired:
        rows = conn.execute(
            """
            SELECT severity, COUNT(*) AS n, MIN(created_at) AS oldest
              FROM notifications
             WHERE wing_inbox_read_at IS NULL AND superseded_at IS NULL
             GROUP BY severity
            """
        ).fetchall()
    else:
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

    # Only the loud ones are re-evaluated: they are what this reader reports,
    # and re-deciding 27 `info` rows would cost more than it tells anyone.
    # NAMING, because the two live one screen apart and mean different things:
    #   superseded  = a SUCCESSOR replaced this row (the DB column, above)
    #   provably_stale = this row's own claim was RE-DECIDED against the
    #                    queue and no longer holds (fee 26, _still_holds)
    provably_stale = 0
    unknown = 0
    loud_rows = conn.execute(
        """
        SELECT origin_plugin, origin_agent, metadata_json
          FROM notifications
         WHERE wing_inbox_read_at IS NULL AND superseded_at IS NULL
           AND severity IN ('critical', 'high')
        """
    ).fetchall() if retired else conn.execute(
        """
        SELECT origin_plugin, origin_agent, metadata_json
          FROM notifications
         WHERE wing_inbox_read_at IS NULL AND severity IN ('critical', 'high')
        """
    ).fetchall()
    for row in loud_rows:
        verdict = _still_holds(row)
        if verdict is False:
            provably_stale += 1
        elif verdict is None:
            unknown += 1

    return {
        "total": sum(by_severity.values()),
        "by_severity": by_severity,
        "critical_or_high": loud,
        "critical_or_high_provably_stale": provably_stale,
        "critical_or_high_unresolvable": unknown,
        "critical_or_high_live": loud - provably_stale,
        "supersede_column_present": retired,
        "oldest": oldest,
        "oldest_age": _age(_parse_iso(oldest)),
    }


#: An agent session opens `running` and is closed by the run that ends. If the
#: run dies between those two writes the row stays `running` for ever, and a row
#: that will never finish is byte-identical to one in progress.
#:
#: WHY THIS READER CARRIES IT, 2026-08-22. `tools/agent-status.py` already
#: flagged surveyor `ae3b3024` — open 77 hours, no process alive, a second
#: session opened 15 seconds after it — with the words "OPEN LONGER THAN THE
#: WALL CLOCK; likely orphaned". It was right and nobody saw it, because
#: CLAUDE.md tells every operator and agent to start with THIS file, and this
#: file did not carry the fact. An orphan is a STATE, and the estate's own
#: doctrine is that state belongs to the state reader; agent-status is the
#: detail view you open once you know to look.
#:
#: The ceiling is deliberately generous. `max_runtime_s` on the agent jobs is
#: 3600, so anything past four hours has outlived every legitimate run by an
#: hour and is not a slow agent.
ORPHAN_AFTER_HOURS = 4


def orphaned_sessions(conn: sqlite3.Connection) -> list[dict]:
    try:
        rows = conn.execute(
            """
            SELECT uuid, agent_name, started_at, trigger, model_uri
              FROM agent_sessions
             WHERE status IN ('running', 'pending') AND ended_at IS NULL
             ORDER BY started_at
            """
        ).fetchall()
    except sqlite3.Error:
        # The table is Wing's; an older schema is an UNKNOWN, never a green.
        return []

    out: list[dict] = []
    for row in rows:
        started = _parse_iso(row["started_at"])
        if started is None:
            continue
        hours = (_now() - started).total_seconds() / 3600
        if hours < ORPHAN_AFTER_HOURS:
            continue  # still plausibly working
        out.append({
            "uuid": row["uuid"],
            "agent": row["agent_name"],
            "trigger": row["trigger"],
            "model_uri": row["model_uri"],
            "started_at": row["started_at"],
            "age": _age(started),
            "hours": round(hours, 1),
        })
    return out


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


def restore_drill() -> dict | None:
    """The drill's OWN verdict, which is not the same fact as its last Pulse run.

    MEASURED 2026-08-22, and it cost six days of false red. The Sunday drill
    failed once on 2026-08-16 07:38 — a 346 MB `keap-db` fetch aborted after ten
    seconds while the 74 MB `wing-db` fetch beside it took six and passed, i.e.
    transient. It was re-run BY HAND at 11:07 the same morning and passed
    (`keap-db: OK (1710/5084/365)`), and again on 2026-08-19 (`1711/5084/367`).
    `~/.nos/backup-verify.json` has said `success: true` for both artifacts ever
    since.

    `failing_jobs()` never saw any of that, because a manual run leaves no
    `pulse_runs` row: it reads the last SCHEDULED run, which is still the failure.
    For a weekly job that is up to seven days of reporting a defect that was
    repaired within four hours — and the repair is invisible precisely because
    the operator did it himself.

    The estate's own doctrine is that a success marker must be written by a
    reader rather than by the attempting code, and this file honours it: the
    drill writes its result, this reads it. What was missing is that nothing
    read the artifact at all, so the schedule was standing in for the outcome.

    NOT a replacement for `failing_jobs()`. A drill that has not run in a month
    is still a finding — hence `stale`, checked against the artifact's own
    timestamp rather than against a job row.
    """
    path = pathlib.Path.home() / ".nos" / "backup-verify.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    artifacts = data.get("artifacts") or []
    failed = [a.get("name") for a in artifacts if not a.get("success")]
    stamp = data.get("checked_at")
    when = (datetime.fromtimestamp(stamp, timezone.utc)
            if isinstance(stamp, (int, float)) else None)
    return {
        "backup_date": data.get("backup_date"),
        "artifacts": len(artifacts),
        "failed": failed,
        "checked_at": when.isoformat() if when else None,
        "age": _age(when),
        # A weekly job gets a fortnight before absence is itself the finding.
        "stale": when is None or when < _now() - timedelta(days=14),
    }


def stalled_verdicts() -> dict | None:
    """Passed loop verdicts whose patch never reached the tree.

    Added 2026-08-19, after two proposals passed every judge on 08-16 and sat
    for three days with both queue rows still `pending` and nothing saying so.
    The loop not applying is by design (docs/idea/11-agentic-loop-contract.md
    §7 non-goal 5); the waiting being invisible is not, and invisible waiting is
    exactly the state this file was written to end.

    Delegates to `tools/loop-status.py::awaiting()` rather than re-deriving the
    join — a second implementation of "is this patch in the tree" is a second
    thing to be wrong. Returns None when that reader cannot load, so the caller
    reports UNKNOWN instead of green.
    """
    sys.path.insert(0, str(REPO / "tools"))
    try:
        import importlib.util  # noqa: PLC0415

        spec = importlib.util.spec_from_file_location(
            "_loop_status", REPO / "tools" / "loop-status.py")
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        report = mod.awaiting()
        if report.get("error"):
            return None
        return {
            "unlanded": [
                {"weakness_id": r["weakness_id"], "state": r["state"],
                 "uuid": r["uuid"][:8], "verdict_at": r["verdict_at"]}
                for r in report.get("unlanded", [])
            ],
        }
    except Exception:  # noqa: BLE001 — any failure is the same answer: cannot ask
        return None
    finally:
        sys.path.remove(str(REPO / "tools"))


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
            report["orphaned_sessions"] = orphaned_sessions(conn)
        conn.close()

    for label, path, fn in (
        ("security_scan", SCAN_STATE, security_scan),
        ("backups", BACKUP_STATUS, backups),
        ("loop_verdicts", REPO / "tools" / "loop-status.py", stalled_verdicts),
        ("restore_drill", pathlib.Path.home() / ".nos" / "backup-verify.json", restore_drill),
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
        # A JOB REPAIRED BY HAND LEAVES NO `pulse_runs` ROW. The restore drill
        # failed once on a transient fetch (2026-08-16), was re-run manually the
        # same morning and passed, and passed again on 08-19 — and this reader
        # kept calling it red for six days, because the last SCHEDULED run is
        # still the failure. The drill writes its own verdict; prefer it, and say
        # both facts rather than silently picking one.
        if job["job"].endswith("backup-restore-drill"):
            drill = report.get("restore_drill") or {}
            drill_when = _parse_iso(drill.get("checked_at"))
            job_when = _parse_iso(job.get("fired_at"))
            newer = drill_when and job_when and drill_when > job_when
            if newer and not drill.get("failed") and not drill.get("stale"):
                out.append(
                    f"{job['job']} last SCHEDULED run failed ({job['age']}) but the "
                    f"drill has passed since — backup-verify.json says "
                    f"{drill['artifacts']}/{drill['artifacts']} ok for backup set "
                    f"{drill.get('backup_date')} ({drill['age']}). Not red; the next "
                    f"scheduled run will clear the row."
                )
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
    loop = report.get("loop_verdicts") or {}
    if loop.get("unlanded"):
        rows = loop["unlanded"]
        # Two different stalls, and one sentence cannot carry both: a passed
        # proposal waits on an ACT, an unjudged one waits on a VERDICT. Saying
        # "passed the judges" of a row no judge has seen is the kind of quiet
        # inaccuracy that makes a reader stop trusting the rest of the line.
        unjudged = [r for r in rows if r["state"] == "unjudged"]
        passed = [r for r in rows if r["state"] != "unjudged"]
        if passed:
            out.append(
                f"{len(passed)} loop proposal(s) passed the judges and never "
                f"reached the tree: "
                + ", ".join(f"{r['weakness_id']} [{r['state']}]" for r in passed[:4])
            )
        if unjudged:
            out.append(
                f"{len(unjudged)} loop proposal(s) filed and never judged: "
                + ", ".join(r["weakness_id"] for r in unjudged[:4])
            )
    inbox = report.get("inbox") or {}
    # A notification is an EVENT; this file reports STATE. Where the emitter
    # left a measurable claim it is re-decided against the estate as it is now.
    # Three numbers, and none of them is "still true" unless a probe said so —
    # an unverifiable row is UNKNOWN, which is exactly what this reader refuses
    # to render as either red or calm anywhere else.
    live = inbox.get("critical_or_high_live", inbox.get("critical_or_high", 0))
    if live:
        stale = inbox.get("critical_or_high_provably_stale", 0)
        unknown = inbox.get("critical_or_high_unresolvable", 0)
        confirmed = live - unknown
        parts = []
        if confirmed:
            parts.append(f"{confirmed} re-checked and still true")
        if unknown:
            parts.append(f"{unknown} carry no re-checkable claim (UNKNOWN, not cleared)")
        line = (
            f"{live} unread CRITICAL/HIGH in the Wing inbox: " + ", ".join(parts)
            + f" ({inbox['total']} unread total, oldest {inbox['oldest_age']})"
        )
        if stale:
            line += (
                f". A further {stale} were true when sent and are provably not "
                "now — nothing marks them read, so they will sit here for ever"
            )
        out.append(line)
    for orphan in report.get("orphaned_sessions", []):
        # Name the model_uri: an orphan on `cli:unrecorded` cannot even say
        # which backend was answering when it stopped, which is a second fact
        # the operator needs and the first one hides.
        out.append(
            f"agent session {orphan['agent']} {orphan['uuid'][:8]} still "
            f"'running' after {orphan['hours']} h ({orphan['age']}) — "
            f"trigger={orphan['trigger']}, model={orphan['model_uri'] or 'unrecorded'}; "
            f"no run can close it now"
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
