"""Two things every scheduled job must say about itself, and one it must not.

WHY, MEASURED 2026-08-06:

  1. `gitleaks:nightly-scan` exits 1 when it FINDS a secret — its whole purpose
     — and `discovery:contradiction-scan` exits 1 when it finds contradictions.
     On the night it first ran, discovery found four and filed four roadmap
     rows; the scheduler recorded a failure. Wing's rule was `$exit !== 0`, so
     every night that carried news raised a HIGH "job failing", which is the
     shape an operator learns to skim. The notification most worth reading was
     the one most likely to be ignored.

  2. Twenty-nine jobs, no purpose anywhere. The operator's catalog was one flat
     list in which a GDPR deadline scan, a knowledge-corpus feeder and an LLM
     agent were indistinguishable rows.

BOTH ARE DECLARED PER JOB, not per plugin and not globally. `conductor` alone
owns a vulnerability scan, a drift watcher and an LLM self-test; bucketing by
plugin would put all three in one box. And exit codes disagree between tools —
gitleaks says 1 for findings, ansible-lint says 2 for violations and 1 for its
own crash — so a single estate-wide convention has to be wrong for someone.
`state/judge-sets.yml` learned this first; the vocabulary is borrowed from it.

WHAT THIS DOES NOT DO: it does not check that a declared findings code is the
RIGHT one. That is a claim about a third-party tool's behaviour, and the only
honest way to hold it is to run the tool. This gate holds the declaration.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]

#: The closed set. A new one is a deliberate edit here plus a look at whether
#: the existing six really failed to fit — categories multiply quietly, and a
#: taxonomy with a bucket per job groups nothing.
CATEGORIES = {"security", "compliance", "knowledge", "platform", "notification", "agents"}

SOURCES = ("files/anatomy/plugins/*/plugin.yml", "files/anatomy/agents/*/agent.yml")


def _jobs() -> list[tuple[str, str, dict]]:
    """(source file, job id, job block) for every declared pulse job.

    BOTH sources, because discover-pulse-catalog.py harvests both — a job in an
    agent profile that this walk missed would look classified when it is not.
    """
    out = []
    for pattern in SOURCES:
        for path in sorted(REPO.glob(pattern)):
            try:
                doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError:
                continue
            if not isinstance(doc, dict):
                continue
            jobs = (doc.get("pulse") or {}).get("jobs") or []
            owner = re.sub(r"-base$", "", str(doc.get("name") or doc.get("agent_id") or path.stem))
            for job in jobs:
                if isinstance(job, dict) and job.get("name"):
                    out.append((str(path.relative_to(REPO)), f"{owner}:{job['name']}", job))
    return out


def test_the_walk_finds_the_jobs():
    """Positive control — the live catalog had 29 on 2026-08-06."""
    jobs = _jobs()
    assert len(jobs) >= 25, f"only {len(jobs)} pulse jobs found; the walk is not covering both sources"
    owners = {jid.split(":")[0] for _, jid, _ in jobs}
    assert "conductor" in owners, "agent profiles are not being walked"
    assert "wing" in owners, "plugin manifests are not being walked"


@pytest.mark.parametrize("src,jid,job", _jobs(), ids=[j[1] for j in _jobs()])
def test_every_job_declares_a_category(src, jid, job):
    category = job.get("category")
    assert category, (
        f"{jid} ({src}) declares no category. It will render in the face's "
        f"'uncategorised' group — which is deliberate and visible rather than "
        f"silently bucketed, but it is still a job nobody classified."
    )
    assert category in CATEGORIES, (
        f"{jid} declares category {category!r}, which is not one of "
        f"{sorted(CATEGORIES)}. Adding a category is an edit to this gate too."
    )


@pytest.mark.parametrize("src,jid,job", _jobs(), ids=[j[1] for j in _jobs()])
def test_findings_exit_codes_are_a_narrow_claim(src, jid, job):
    codes = job.get("findings_exit_codes")
    if codes is None:
        return  # not declaring is the default and keeps the original rule
    assert isinstance(codes, list) and codes, (
        f"{jid}: findings_exit_codes must be a non-empty list; {codes!r} would "
        f"read as 'declared nothing' and silently restore the old behaviour"
    )
    assert all(isinstance(c, int) for c in codes), f"{jid}: codes must be integers, got {codes!r}"
    assert 0 not in codes, (
        f"{jid} declares 0 as a findings code. Zero already means success; "
        f"listing it would turn an ordinary pass into a special case."
    )
    assert len(codes) <= 3, (
        f"{jid} declares {len(codes)} findings codes. This is meant to name the "
        f"one or two a tool documents, not to widen 'non-zero is fine' until "
        f"the job can no longer fail — which removes the alarm rather than "
        f"sharpening it."
    )


def test_the_consumers_actually_read_both_fields():
    """A declaration nothing reads is decoration.

    Each of these was a real gap on the way in: the POST body is an allow-list
    (it dropped args[] in May the same way), and the projection is an
    allow-list too, by design.
    """
    post = (REPO / "roles/pazny.wing/tasks/post.yml").read_text(encoding="utf-8")
    for field in ("findings_exit_codes", "category"):
        assert field in post, (
            f"the pulse_jobs POST body omits {field}, so the manifest declares "
            f"it and Wing never receives it"
        )
    repo_php = (REPO / "files/anatomy/wing/app/Model/PulseRepository.php").read_text(encoding="utf-8")
    assert "findingsExitCodes" in repo_php, "Wing cannot read a job's findings codes"
    presenter = (REPO / "files/anatomy/wing/app/Presenters/Api/PulsePresenter.php").read_text(encoding="utf-8")
    assert "findingsExitCodes" in presenter, (
        "the notification path no longer consults the declared codes — every "
        "findings night is a 'job failing' again"
    )
    projection = (REPO / "files/anatomy/face/src/lib/anatomy/pulse.ts").read_text(encoding="utf-8")
    for field in ("findings_exit_codes", "category"):
        assert field in projection, f"the face projection drops {field}"
