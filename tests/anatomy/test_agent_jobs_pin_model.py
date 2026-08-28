"""Anatomy gate — every scheduled agent ceremony pins its model tier.

pulse-run-agent.sh: "Without it claude falls back to the operator's default —
the most expensive tier — which bulk jobs like taxonomy-describe must never
inherit." Six jobs (drift-scan, promote-migration, self-test-001, recipe-author,
upgrade-advise, triage-open-findings) shipped WITHOUT NOS_AGENT_MODEL and silently
ran at the top tier (readiness item 3, 2026-08-12).

The invariant this pins: any pulse job that invokes pulse-run-agent.sh carries an
NOS_AGENT_MODEL env pin, and the pin is one of the known CLI aliases. It does NOT
dictate WHICH tier — that is a per-ceremony judgement recorded in each manifest —
only that the choice was made deliberately rather than left to the default.

CI-safe: pure YAML source scan; no Docker, no live host.
"""
from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
AGENTS_DIR = REPO / "files" / "anatomy" / "agents"
RUNNER = "run-agent.sh"   # matches both the bound runner and the legacy CLI one
# Aliases the claude CLI --model flag accepts; the librarian precedent uses these.
VALID_TIERS = {"haiku", "sonnet", "opus"}


def _agent_files() -> list[pathlib.Path]:
    return sorted(AGENTS_DIR.glob("*/agent.yml"))


def _agent_runner_jobs():
    """Yield (file, job) for every pulse job that runs an agent ceremony."""
    for f in _agent_files():
        doc = yaml.safe_load(f.read_text()) or {}
        pulse = doc.get("pulse") or {}
        for job in pulse.get("jobs") or []:
            if RUNNER in str(job.get("command", "")):
                yield f, job


def test_there_are_agent_runner_jobs():
    jobs = list(_agent_runner_jobs())
    assert jobs, (
        "no agent profile declares a pulse-run-agent.sh job — path/shape drift? "
        "This gate would pass vacuously otherwise."
    )


def test_every_agent_job_pins_a_model():
    offenders = []
    for f, job in _agent_runner_jobs():
        env = job.get("env") or {}
        model = env.get("NOS_AGENT_MODEL")
        if not model:
            offenders.append(
                f"{f.parent.name}:{job.get('name')} — no NOS_AGENT_MODEL; falls to the "
                f"operator default (the most expensive tier)"
            )
        elif str(model).strip() not in VALID_TIERS:
            offenders.append(
                f"{f.parent.name}:{job.get('name')} — NOS_AGENT_MODEL={model!r} is not a "
                f"known tier {sorted(VALID_TIERS)}"
            )
    assert not offenders, "Unpinned or invalid agent model tiers:\n  " + "\n  ".join(
        offenders
    )
