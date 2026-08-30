"""Two jobs that take the same exclusive agent lock may not have overlapping windows.

MEASURED 2026-08-30, from the Pulse log, in local time:

    04:12:34  conductor:vulnerability-scan start
    04:13:04  librarian:describe-taxonomy   start
    04:18:16  librarian:describe-taxonomy   done rc=2   (waited 311s for the lock)
    04:19:50  conductor:vulnerability-scan  done rc=0   (held it for 435s)

Thirty seconds apart. The loser waits for the mkdir mutex, times out, exits 2,
and is red until its next cron — roughly a day later. Nothing retried it.

WHY A GATE AND NOT A CAREFUL AUTHOR. This exact pair had ALREADY been moved
once for this exact reason: `describe-taxonomy` went 02:10 -> 02:30 earlier the
same day, and its comment shows the reasoning — the scan "averages 607s with a
measured worst case of 1080s". Twenty minutes of separation covers 1080s. It
collided that night anyway, because the scan's DECLARED ceiling is 1800s with
15 minutes of jitter and it is allowed to run until 02:45.

That is the rule this file exists to hold: **a margin sized to what a job has
done so far is not a margin.** Size it to what the job is allowed to do —
`schedule` + `jitter_min` + `max_runtime_s`, all three declared right there in
the manifest, none of them requiring anyone to remember a measurement.

WHAT IT DOES NOT CLAIM. It compares daily jobs against daily jobs and weekly
against everything, on minute-of-day; a job with a day-of-month or month field
is not modelled and is reported as unmodelled rather than silently passed. It
also assumes the lock is exclusive across every command in
`AGENT_LOCK_COMMANDS` — which is what `tools/anatomy-graph-gen.py` already
declares, read from there rather than restated here so the two cannot drift.
"""

from __future__ import annotations

import pathlib
import re

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
AGENTS = REPO / "files/anatomy/agents"
PLUGINS = REPO / "files/anatomy/plugins"
GRAPH_GEN = REPO / "tools/anatomy-graph-gen.py"


def _lock_commands() -> tuple[str, ...]:
    """From the graph generator's own declaration, not a copy of it."""
    src = GRAPH_GEN.read_text(encoding="utf-8")
    found = re.search(r"AGENT_LOCK_COMMANDS\s*=\s*\(([^)]*)\)", src, re.S)
    assert found, "AGENT_LOCK_COMMANDS is gone from tools/anatomy-graph-gen.py"
    cmds = tuple(re.findall(r'"([^"]+)"', found.group(1)))
    assert cmds, "AGENT_LOCK_COMMANDS parsed empty — the gate would compare nothing"
    return cmds


def _jobs() -> list[dict]:
    """Every declared pulse job that takes the exclusive agent lock."""
    cmds = _lock_commands()
    out: list[dict] = []
    for path in sorted(AGENTS.glob("*/agent.yml")) + sorted(PLUGINS.glob("*/plugin.yml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for key in ("pulse_jobs", "pulse"):
            jobs = doc.get(key)
            if isinstance(jobs, dict):
                jobs = jobs.get("jobs")
            for job in (jobs or []):
                if not isinstance(job, dict) or not job.get("schedule"):
                    continue
                if job.get("paused"):
                    continue
                command = str(job.get("command", ""))
                if not any(c in command for c in cmds):
                    continue
                out.append({
                    "id": f"{path.parent.name}:{job['name']}",
                    "schedule": str(job["schedule"]),
                    "jitter_min": int(job.get("jitter_min", 0) or 0),
                    "max_runtime_s": int(job.get("max_runtime_s", 0) or 0),
                })
    return out


def _window(job: dict) -> tuple[int, int, str] | None:
    """(earliest start, latest end) in minutes-of-day, plus the day-of-week
    field. None when the cron shape is not modelled here."""
    parts = job["schedule"].split()
    if len(parts) != 5:
        return None
    minute, hour, dom, month, dow = parts
    if not (minute.isdigit() and hour.isdigit()):
        return None
    if dom != "*" or month != "*":
        return None
    start = int(hour) * 60 + int(minute)
    end = start + job["jitter_min"] + -(-job["max_runtime_s"] // 60)  # ceil to minutes
    return start, end, dow


def _days_can_coincide(a: str, b: str) -> bool:
    """Two day-of-week fields that can name the same day. `*` meets anything."""
    if a == "*" or b == "*":
        return True
    return bool({s.strip() for s in a.split(",")} & {s.strip() for s in b.split(",")})


def test_there_are_lock_taking_jobs_to_compare() -> None:
    """Guard against the vacuous pass: a parser change that finds nothing would
    make every assertion below true."""
    jobs = _jobs()
    assert len(jobs) >= 4, (
        f"only {len(jobs)} agent-lock job(s) found; the manifests declare more "
        "than that, so the parser has stopped seeing them")


def test_no_two_windows_overlap() -> None:
    jobs = [j for j in _jobs() if _window(j)]
    fail = []
    for i, first in enumerate(jobs):
        a_start, a_end, a_dow = _window(first)
        for second in jobs[i + 1:]:
            b_start, b_end, b_dow = _window(second)
            if not _days_can_coincide(a_dow, b_dow):
                continue
            if a_start < b_end and b_start < a_end:
                lo, hi = sorted(((a_start, a_end, first), (b_start, b_end, second)))[:2]
                fail.append(
                    f"{first['id']} [{a_start // 60:02d}:{a_start % 60:02d}"
                    f"–{a_end // 60:02d}:{a_end % 60:02d}] overlaps "
                    f"{second['id']} [{b_start // 60:02d}:{b_start % 60:02d}"
                    f"–{b_end // 60:02d}:{b_end % 60:02d}]")
    assert not fail, (
        "these jobs take the same exclusive agent lock and their declared "
        "windows (schedule + jitter_min + max_runtime_s) overlap. The loser "
        "waits for the mutex, times out and exits 2, and stays red until its "
        "next cron:\n  " + "\n  ".join(fail))


def test_an_unmodelled_schedule_is_reported_not_ignored() -> None:
    """A cron shape this gate cannot reason about must be visible. Silently
    skipping it is how a job slips out of a constraint it still belongs to."""
    unmodelled = [j["id"] for j in _jobs() if _window(j) is None]
    assert not unmodelled, (
        "these agent-lock jobs use a cron shape this gate does not model "
        "(ranges, steps, day-of-month), so their overlap is UNCHECKED rather "
        "than proven absent — extend _window() or say here why it is safe: "
        + ", ".join(unmodelled))
