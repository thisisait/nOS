"""A scheduled consumer must fire after the scheduled job that fills it.

MEASURED 2026-08-30 across the whole run history, every night without exception:

    librarian:judge-lint-queue   fired 05:11 – 05:14
    keap:keap-lint               fired 05:15 – 05:18

`keap-lint` is what PUTS findings in the lint queue. The judge was scheduled
`10 5 * * *` and the producer `15 5 * * *`, so for the entire life of these
schedules the judge ruled on the PREVIOUS night's queue. It exited 0, wrote
verdicts, and no reader could tell — a verdict on stale input is
indistinguishable from a verdict on fresh input once it is written down.

Nothing caught it because nothing in the estate models the ORDER of the nightly
jobs. `tools/anatomy-measure-margins.py` measures gaps between declared edges of
the keap/cortex chain; this pair is not one of its edges, and a margin tool asks
"is there enough time between them", never "are they the right way round".

WHAT THIS GATE IS AND IS NOT. It is not a dependency graph — the estate has no
declaration of which job feeds which, and inventing one to satisfy a test would
be a second source of truth about the schedule. It pins the ONE ordering that
was measured wrong, by name, with its margin, so a future edit to either cron
has to think about the other. When a second pair earns an entry, that is the
moment to ask whether the declaration is worth building.

Retro-verified 2026-08-30 by restoring `10 5 * * *`.
"""

from __future__ import annotations

import pathlib
import re

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
LIBRARIAN = REPO / "files/anatomy/agents/librarian/agent.yml"
KEAP_PLUGIN = REPO / "files/anatomy/plugins/keap-base/plugin.yml"

#: keap-lint's measured worst case, 25 runs: avg 19s, max 21s. The margin the
#: consumer needs is that plus room for the producer to slow down.
PRODUCER_WORST_S = 21


def _minutes(cron: str) -> int:
    """Minute-of-day for a `m h * * *` expression. None-safe by exploding."""
    minute, hour = cron.split()[:2]
    assert minute.isdigit() and hour.isdigit(), f"not a fixed daily time: {cron!r}"
    return int(hour) * 60 + int(minute)


def _pulse_job(path: pathlib.Path, name: str) -> dict:
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    for block in ("pulse_jobs", "pulse"):
        for job in (doc.get(block) or []):
            if isinstance(job, dict) and job.get("name") == name:
                return job
    # keap-base nests its jobs under a different key shape; fall back to a
    # scan so this gate does not depend on one manifest's layout.
    # Text fallback for a manifest whose pulse block this loader does not
    # model. It must carry `paused` too: a first draft returned only the
    # schedule, so `job.get("paused")` was always False and the paused-producer
    # assertion below could never fire — a gate blind in exactly the direction
    # that makes every future judgement stale.
    body = path.read_text(encoding="utf-8")
    found = re.search(rf"name:\s*{re.escape(name)}\b(.*?)(?=\n\s*- name:|\Z)", body, re.S)
    assert found, f"no pulse job {name!r} in {path.name}"
    block = found.group(1)
    sched = re.search(r"schedule:\s*\"([^\"]+)\"", block)
    assert sched, f"pulse job {name!r} has no schedule in {path.name}"
    return {"name": name, "schedule": sched.group(1),
            "paused": bool(re.search(r"paused:\s*true", block))}


def test_the_judge_fires_after_the_lint_that_fills_its_queue() -> None:
    judge = _minutes(_pulse_job(LIBRARIAN, "judge-lint-queue")["schedule"])
    lint = _minutes(_pulse_job(KEAP_PLUGIN, "keap-lint")["schedule"])
    assert judge > lint, (
        f"librarian:judge-lint-queue fires at {judge // 60:02d}:{judge % 60:02d} "
        f"and keap:keap-lint — which FILLS the queue it judges — at "
        f"{lint // 60:02d}:{lint % 60:02d}. The judge would rule on the previous "
        "night's queue, exit 0, and write verdicts nobody can tell apart from "
        "fresh ones. This was the live state until 2026-08-30.")
    margin = judge - lint
    # Five minutes, not "twice the producer's 21s". A margin sized to today's
    # measurement leaves nothing for the day the producer is slow, and the cost
    # of being wrong here is a silent verdict on stale input — the whole defect.
    assert margin >= 5, (
        f"only {margin} min between them; keap-lint's measured worst is "
        f"{PRODUCER_WORST_S}s but a margin sized to that leaves no room for a "
        "slow night, and the failure is silent")


def test_both_jobs_are_still_daily_and_unpaused() -> None:
    """The gate above is vacuous if either job stops running. A paused producer
    makes every future judgement stale in a way no ordering can fix."""
    for path, name in ((LIBRARIAN, "judge-lint-queue"), (KEAP_PLUGIN, "keap-lint")):
        job = _pulse_job(path, name)
        assert job["schedule"].split()[2:] == ["*", "*", "*"], (
            f"{name} is no longer daily ({job['schedule']!r}) — re-read this gate")
        assert not job.get("paused", False), f"{name} is paused; the pair means nothing"
