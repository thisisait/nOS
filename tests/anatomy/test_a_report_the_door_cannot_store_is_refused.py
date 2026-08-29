"""A 201 that stores nothing is the success marker written by the thing that failed.

MEASURED 2026-08-29, session `be9d107f`. The librarian did its work — four brief
proposals POSTed to KEAP — then filed its report twice, was answered **201** both
times, and both rows stored `length(result_json) = 0`. It had put the markdown
under `body`; two other attempts wrapped the whole payload in `event`. With
`result` and `result_json` already accepted, that is FOUR spellings for one
field, arrived at by four different guesses from two models.

The tempting fix is a fifth alias. It is the wrong one: every alias teaches the
next model that a new spelling is fine, and the door goes on accepting reports
whose content it silently drops. So the door refuses instead, and names the field
it will store.

That is safe to do because the agent demonstrably ACTS on a 400 — in this very
session it read "Missing required field(s): ts, run_id" and got the fields right
on a later attempt. What it never learned was that its body was being discarded,
because nothing told it.

Scope, deliberately narrow: only `conductor_report`, the type a ceremony owes.
Most event types legitimately carry no body and must stay accepted without one.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
WING = REPO / "files/anatomy/wing"
AGENTS = REPO / "files/anatomy/agents"
PRESENTER = WING / "app/Presenters/Api/EventsPresenter.php"


def test_only_the_report_type_is_held_to_it() -> None:
    """A blanket body requirement would refuse every ordinary event."""
    src = PRESENTER.read_text(encoding="utf-8")
    i = src.index("a conductor_report must carry its body")
    guard = src[max(0, i - 900):i]
    assert "'conductor_report'" in guard, (
        "the body requirement is no longer scoped to the report type; ordinary "
        "events carry no body and would start being refused"
    )


def test_the_refusal_names_the_field_it_will_store() -> None:
    """A refusal that does not say what to send is a wall, not a contract."""
    src = PRESENTER.read_text(encoding="utf-8")
    i = src.index("a conductor_report must carry its body")
    msg = src[i:i + 500]
    assert "result_json" in msg and "report_markdown" in msg, (
        "the 400 does not name the accepted key; the agent has nothing to act on"
    )
    assert "would have" in msg or "recorded empty" in msg, (
        "the refusal does not say what WOULD have happened, which is the part "
        "that makes it worth a round trip"
    )


def test_both_accepted_spellings_still_pass_the_guard() -> None:
    """`result` is what in-process writers send; `result_json` is what the
    prompts say. Refusing either would break a working path."""
    src = PRESENTER.read_text(encoding="utf-8")
    i = src.index("a conductor_report must carry its body")
    guard = src[max(0, i - 900):i]
    assert "'result'" in guard and "'result_json'" in guard


def test_every_report_task_names_the_field() -> None:
    """The measurement that started this: the surveyor's task names
    `result_json.report_markdown` and stored a body on all three M2.7 runs; the
    librarian's did not, and stored none."""
    silent = []
    for d in sorted(AGENTS.iterdir()):
        f = d / "agent.yml"
        if not f.is_file():
            continue
        doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        if not ((doc.get("outcomes") or {}).get("deliverable")):
            continue
        for job in ((doc.get("pulse") or {}).get("jobs") or []):
            if not str(job.get("command", "")).endswith("/tools/run-agent.sh"):
                continue
            task = ((job.get("env") or {}).get("NOS_AGENT_TASK") or "")
            if "/api/v1/events" in task and "result_json" not in task:
                silent.append(f"{d.name}:{job.get('name')}")
    assert not silent, (
        f"these tasks say where to POST but not which field carries the body: "
        f"{silent}. The door now refuses them, which is better than storing "
        f"them empty — but a refusal the task could have prevented is a round "
        f"trip nobody needed."
    )
