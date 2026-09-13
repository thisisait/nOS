"""tools/red-status.py — one row per structured finding, never the prose list.

The reader also emits `reds`: one sentence per finding, for a human terminal.
A table whose cells are those sentences is a log wearing column headers. This
pane maps the JSON keys `collect()` already has.
"""
ID, LABEL, TITLE = "red", "Red", "what is red RIGHT NOW"
READER = "tools/red-status.py"
REFRESH = 30
COLUMNS = ["source", "id", "status", "age", "what"]
DEMO = {
    "red_count": 2,
    "failing_jobs": [
        {"job": "backup:nightly", "age": "15 h ago", "exit_code": 1,
         "last_line": "rsync failed", "fired_at": "2026-09-12T00:00:00+00:00"},
    ],
    "overdue_jobs": [],
    "inbox": {"critical_or_high_live": 11, "critical_or_high_unresolvable": 2,
              "critical_or_high_provably_stale": 4, "total": 40,
              "oldest_age": "24 d ago"},
    "audit_chain": {"ok": True, "unsigned": 37, "checked": 40, "age": "11 h ago"},
    "orphaned_sessions": [],
    "security_scan": {"stale": False, "cycle": 46, "age": "37 h ago",
                      "scan_failed": []},
    "backups": {"stale": False, "sources": 14, "age": "15 h ago", "failed": []},
    "restore_drill": {"stale": False, "age": "6 d ago", "failed": False,
                      "artifacts": 3, "backup_date": "2026-09-12",
                      "checked_at": "2026-09-13T00:00:00+00:00"},
    "loop_verdicts": {"unlanded": [
        {"weakness_id": "w-1", "state": "passed"},
    ]},
    "ci": {},
    "dependabot": {"counts": {}, "serious_packages": []},
    "sources_missing": [],
    "reds": ["this prose must never become a row"],
}


def _row(source, ident, status, age="", what=""):
    return {"source": source, "id": ident, "status": status, "age": age, "what": what}


def _fresh(key, sub, ok_when):
    if sub is None:
        return _row(key, key, "UNKNOWN", "", "source missing — not the same as fine")
    bad = not ok_when(sub)
    return _row(key, key, "STALE" if bad else "OK", sub.get("age", ""),
                ", ".join(f"{k}={v}" for k, v in sub.items() if k != "age"))


def build_rows(data):
    rows = []
    chain = data.get("audit_chain")
    chain_broken = bool(chain and chain.get("ok") is False)
    if chain_broken:
        rows.append(_row("audit", "audit-chain", "BROKEN", chain.get("age", ""),
                         f"unsigned {chain.get('unsigned')} of {chain.get('checked')}"))

    drill = data.get("restore_drill") or {}
    for job in data.get("failing_jobs") or []:
        name = job.get("job") or ""
        if chain_broken and name.endswith("audit-chain-verify"):
            continue
        if name.endswith("backup-restore-drill"):
            drill_when = drill.get("checked_at") or ""
            job_when = job.get("fired_at") or ""
            if (drill_when and job_when and drill_when > job_when
                    and not drill.get("failed") and not drill.get("stale")):
                rows.append(_row("job", name, "CLEARED", job.get("age", ""),
                                 "scheduled fail, later drill passed"))
                continue
        rows.append(_row("job", name, "FAIL", job.get("age", ""),
                         f"rc={job.get('exit_code')} {job.get('last_line') or ''}".strip()))

    scan = data.get("security_scan")
    if scan and scan.get("scan_failed"):
        failed = scan["scan_failed"]
        rows.append(_row("scan", "security_scan", "FAIL", scan.get("age", ""),
                         f"{len(failed)} scan_failed: {', '.join(failed[:6])}"))

    bk = data.get("backups")
    if bk and bk.get("failed"):
        rows.append(_row("backup", "backups", "FAIL", bk.get("age", ""),
                         ", ".join(str(f) for f in bk["failed"])))

    for job in data.get("overdue_jobs") or []:
        rows.append(_row("due", job.get("job", ""), "OVERDUE",
                         job.get("overdue_by", ""),
                         f"due {job.get('due_at')} `{job.get('schedule')}`"))

    for item in (data.get("loop_verdicts") or {}).get("unlanded") or []:
        rows.append(_row("loop", item.get("weakness_id", ""),
                         (item.get("state") or "unlanded").upper(),
                         "", "proposal not on the tree"))

    inbox = data.get("inbox") or {}
    live = inbox.get("critical_or_high_live", inbox.get("critical_or_high", 0))
    if live:
        rows.append(_row(
            "inbox", "wing-inbox", "RED", inbox.get("oldest_age", ""),
            f"{live} unread C/H, {inbox.get('total', 0)} unread total"))

    for orphan in data.get("orphaned_sessions") or []:
        rows.append(_row("agent", f"{orphan.get('agent')} {str(orphan.get('uuid', ''))[:8]}",
                         "ORPHAN", orphan.get("age", ""),
                         f"{orphan.get('hours')}h {orphan.get('trigger')} {orphan.get('model_uri') or ''}"))

    for branch, failures in (data.get("ci") or {}).items():
        for f in failures or []:
            rows.append(_row("ci", f.get("workflow", ""), f.get("conclusion", "red").upper(),
                             "", f"{branch} {f.get('sha', '')}"))

    dep = data.get("dependabot")
    if dep and dep.get("counts"):
        tally = ", ".join(f"{n} {sev}" for sev, n in sorted(dep["counts"].items()))
        rows.append(_row("dep", "dependabot", "OPEN", "", tally))

    for missing in data.get("sources_missing") or []:
        rows.append(_row("source", missing, "UNKNOWN", "", "unreadable"))

    rows.append(_fresh("backups", data.get("backups"),
                       lambda s: s.get("stale") is not True and not s.get("failed")))
    rows.append(_fresh("audit_chain", data.get("audit_chain"),
                       lambda s: s.get("ok") is not False))
    rows.append(_fresh("security_scan", data.get("security_scan"),
                       lambda s: s.get("stale") is not True and not s.get("scan_failed")))
    rows.append(_fresh("restore_drill", data.get("restore_drill"),
                       lambda s: s.get("stale") is not True and not s.get("failed")))
    return rows


def meta(data):
    return {"red_count": data.get("red_count"), "generated_at": data.get("generated_at")}
