"""Anatomy CI gate — active-work.md stays a pointer, not an archive.

Phase A of the devlog epic (2026-06-12) cut docs/active-work.md from 522
lines of archaeology to a NOW-only pointer; narrative history belongs in the
devlog (docs/devlog/README.md), completed plans in docs/archive/. This gate
pins the ceiling so the file cannot silently regress into a changelog.
"""
from __future__ import annotations

import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
ACTIVE_WORK = REPO / "docs/active-work.md"
CEILING = 150


def test_active_work_under_ceiling():
    lines = ACTIVE_WORK.read_text(encoding="utf-8").count("\n")
    assert lines <= CEILING, (
        f"docs/active-work.md is {lines} lines (ceiling {CEILING}) — move the "
        "narrative to a devlog entry (/devlog new) and keep this file NOW-only"
    )


def test_active_work_points_at_the_devlog():
    text = ACTIVE_WORK.read_text(encoding="utf-8")
    assert "devlog" in text, "the pointer doctrine paragraph went missing"
