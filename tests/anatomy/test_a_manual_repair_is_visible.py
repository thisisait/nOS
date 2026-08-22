"""Gate — a job repaired by hand must not keep reading as red.

THE FEE THIS PINS: docs/hidden_fees/19-a-repair-the-reader-cannot-see.md.

`red-status.py`'s `failing_jobs()` reads `pulse_runs` and takes each job's most
recent run. A manual invocation leaves no row there, so the restore drill — which
failed once on a transient fetch on 2026-08-16, was re-run by hand four hours
later and passed, and passed again on 08-19 — kept reading as red for six days.

The cost was not the noise. `docs/Q2-2026-plan.md` was written that morning with
"diagnose the restore drill" as item 0 of the quarter, on the correct reasoning
that a red drill gates the `sec-p1` blank. The premise was false and the plan
said so in writing, because every reader in the chain asked the tool CLAUDE.md
tells them to ask first. An alarm that cries wolf reorders work.

WHAT IS ASSERTED, and deliberately not more: that the reader CONSULTS the drill's
own artifact, that it keeps naming the job rather than silently dropping it, and
that absence of the artifact is not read as health. Whether the drill itself
passes is the drill's business — this gate would be worthless if it required a
green estate to pass.
"""
from __future__ import annotations

import pathlib
import re

READER = pathlib.Path(__file__).resolve().parents[2] / "tools" / "red-status.py"


def _source() -> str:
    return READER.read_text(encoding="utf-8")


def test_the_reader_reads_the_drills_own_verdict() -> None:
    src = _source()
    assert "backup-verify.json" in src, (
        "red-status.py does not read ~/.nos/backup-verify.json. The drill writes "
        "its outcome there; without it the SCHEDULE stands in for the OUTCOME, "
        "which is how a four-hour repair read as a six-day defect."
    )
    assert re.search(r"def restore_drill\(", src), (
        "the artifact reader is gone — `restore_drill()` is what makes a manual "
        "repair visible"
    )


def test_a_newer_passing_artifact_suppresses_the_stale_failure() -> None:
    """The comparison must be on TIME, not on the mere existence of a green file.

    A drill artifact from before the failure proves nothing, and treating any
    green file as exoneration would be strictly worse than the bug it replaces.
    """
    src = _source()
    # Anchor on the EMITTER, not on the first mention: the string also appears
    # in restore_drill()'s docstring, and the first version of this gate
    # windowed on that and failed against a correct reader.
    reds = src[src.index("def reds(") :]
    window = reds[reds.index("backup-restore-drill") :][:1600]
    assert "checked_at" in window and "fired_at" in window, (
        "the drill carve-out must compare the artifact's timestamp against the "
        "failing run's, so an OLD green artifact cannot excuse a NEW failure"
    )
    assert "stale" in window, (
        "a drill that stopped running is a different finding; the carve-out must "
        "refuse to exonerate on a stale artifact"
    )
    assert re.search(r"drill\.get\(.failed.\)", window), (
        "the carve-out must check the artifact actually passed"
    )


def test_the_job_is_still_named_rather_than_dropped() -> None:
    """Suppressing the line entirely would trade a false red for a silent one."""
    src = _source()
    # Anchor on the EMITTER, not on the first mention: the string also appears
    # in restore_drill()'s docstring, and the first version of this gate
    # windowed on that and failed against a correct reader.
    reds = src[src.index("def reds(") :]
    window = reds[reds.index("backup-restore-drill") :][:1600]
    assert "last SCHEDULED run failed" in window, (
        "the reader must still name the job and its failed scheduled run — "
        "hiding it would replace a wrong answer with no answer"
    )
    assert "passed since" in window, "the line must also carry the newer verdict"


def test_a_missing_artifact_is_not_read_as_health() -> None:
    """`restore_drill()` returns None when the file is absent, and `collect()`
    files that under `sources_missing` — the file's own docstring promises a
    missing source 'says so rather than treating absence as health'."""
    src = _source()
    body = src[src.index("def restore_drill(") :]
    body = body[: body.index("\ndef ", 10)]
    assert "return None" in body, (
        "restore_drill() must return None on an unreadable artifact so collect() "
        "records it as a MISSING source, never as a pass"
    )
    assert "sources_missing" in src
