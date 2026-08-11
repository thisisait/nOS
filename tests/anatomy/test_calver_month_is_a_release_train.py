"""Anatomy gate: a calendar version's MONTH is its major, not its minor.

MEASURED 2026-08-11, during a routine pin sweep. `tools/pin-latest-scan.py`
reported:

    ghcr.io/goauthentik/server   2026.5.2  ->  2026.8   = minor

`minor` is the grade that tool's own docstring describes as "the part a sweep may
take". The row is three release trains of the SSO spine — the service every other
login in the estate depends on — and authentik's schema migrations are
FORWARD-ONLY: CLAUDE.md records that restoring the old dump under new code
half-migrates the schema, so the usual "revert the pin" escape does not exist.

Nothing was wrong with the number; the number was right. The GRADE was wrong,
and the grade is what a sweep reads. Taking that row would have been the single
most expensive edit available that day, and the report would have called it
routine — which is this estate's recurring shape, an overclaim that reads calm.

THE RULE PINNED HERE. When the leading field is a year, the second field is the
release train and a jump across it is `major`. Within one train, a third-field
move is `patch` — `2026.8.0 -> 2026.8.1` must stay sweepable, or the fix has
traded a dangerous false-calm for a useless false-alarm and nobody will trust the
tool either way.

WHY BOTH DIRECTIONS ARE ASSERTED: the file already carries one scar from a
half-fix. `NOT_A_MAJOR` exists because a first cut at 1000 rejected calver
outright and reported authentik and Home Assistant "unpinnable" — "trading one
false reading for another", in its own words. This gate refuses that trade a
second time.

WHAT THIS CANNOT DO: know whether a given month-jump is actually dangerous.
`major` here means "a human decides", not "forbidden".
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
TOOL = REPO / "tools" / "pin-latest-scan.py"


@pytest.fixture(scope="module")
def scan():
    spec = importlib.util.spec_from_file_location("pin_latest_scan", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize(("pinned", "newest", "expected", "why"), [
    # The measured row. Three trains of the SSO spine.
    ("2026.5.2", "2026.8", "major", "authentik, the row that produced this gate"),
    # A year rollover is a train jump too, and the widest one.
    ("2026.12.1", "2027.1.0", "major", "calendar year rollover"),
    # Same train: still sweepable. The half-fix this gate also guards against.
    ("2026.8.0", "2026.8.1", "patch", "Home Assistant, within one train"),
    # Plain semver must be untouched by the calver branch.
    ("12.4.4", "13.1.3", "major", "grafana, ordinary semver major"),
    ("2.34.2", "2.35.0", "minor", "n8n, ordinary semver minor"),
    ("v0.162.16", "v0.162.19", "patch", "infisical, ordinary semver patch"),
])
def test_the_grade_matches_the_risk(scan, pinned, newest, expected, why) -> None:
    got = scan.classify(pinned, newest)
    assert got == expected, (
        f"{pinned} -> {newest} classified `{got}`, expected `{expected}` ({why}). "
        "The grade is what a sweep reads, so an understated grade is an "
        "unreviewed upgrade of whatever that pin happens to be."
    )


def test_a_calver_pin_is_never_graded_minor(scan) -> None:
    """`minor` is the sweep's permission word; calver must never earn it.

    Asserted separately from the table because it is the property, not an
    example: for a calver pin there are only two honest answers — same train
    (patch) or different train (major). A `minor` verdict means the semver
    branch was reached, which is the original defect returning by another route.
    """
    for pinned, newest in (("2026.5.2", "2026.8"), ("2026.1.0", "2026.11.4"),
                           ("2025.12.4", "2026.5.2")):
        assert scan.classify(pinned, newest) != "minor", (
            f"{pinned} -> {newest} graded `minor`. Calendar versions have no "
            "minor grade — the month IS the train. Something reached the semver "
            "branch, and a sweep will treat a train jump as routine."
        )


def test_calver_detection_is_narrow(scan) -> None:
    """A year-shaped leading number, and nothing else.

    Widening this would quietly re-grade ordinary semver majors as trains. The
    range is asserted rather than the implementation so the check survives a
    rewrite of how the branch is expressed.
    """
    assert scan.is_calver(scan.parse("2026.5.2"))
    assert scan.is_calver(scan.parse("2000.1.0"))
    for ordinary in ("1999.1.0", "12.4.4", "0.4.5026", "18.11.7"):
        assert not scan.is_calver(scan.parse(ordinary)), (
            f"{ordinary} was read as a calendar version. It is not, and grading "
            "it as one turns its majors into 'patch' — the failure inverted, "
            "which is worse than the one this gate was written for."
        )


def test_the_tool_still_documents_why_calver_survives_parsing() -> None:
    """The `NOT_A_MAJOR` scar, kept legible.

    That constant is the reason a four-digit year parses at all. Losing its
    explanation is how the next person re-raises the threshold to 1000 and
    reports the SSO spine as unpinnable again.
    """
    text = TOOL.read_text(encoding="utf-8")
    assert "CALENDAR VERSIONING" in text and "NOT_A_MAJOR" in text, (
        "pin-latest-scan.py lost its record of why calendar versions must parse. "
        "The file has already been wrong in both directions on this exact point."
    )
