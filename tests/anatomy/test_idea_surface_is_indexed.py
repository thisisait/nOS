"""Anatomy CI gate — the idea surface is indexed, unique, and under its ratchet.

Fee 51 (audit 2026-09-02, verified 2026-09-03): the index promised a ceiling of
twenty in prose while 24 files existed, two numeric prefixes collided (11, 13)
and eight files were absent from the table — a constraint nobody gated, on the
surface that INVENTED the hidden-fee practice. active-work.md learned this
lesson (test_active_work_slim); the idea surface copied the ceiling, not the
gate.

CEILING is a ratchet: lower it as the absorb/archive pass shrinks the surface;
raising it is the loud act. Target is the doc's own twenty.
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
IDEA = REPO / "docs" / "idea"

#: 2026-09-03: 23 numbered files + the index = 24. Absorb/archive toward 20.
CEILING = 24


def _files() -> list[pathlib.Path]:
    return sorted(f for f in IDEA.glob("*.md") if f.name != "00-index.md")


def test_every_idea_file_is_indexed():
    index = (IDEA / "00-index.md").read_text(encoding="utf-8")
    linked = set(re.findall(r"\]\(([0-9][^)]+\.md)\)", index))
    missing = [f.name for f in _files() if f.name not in linked]
    assert not missing, (
        f"idea file(s) absent from 00-index.md: {missing}. An unindexed idea "
        "doc is invisible to every reader that starts at the index — eight "
        "were, for weeks")


def test_the_ceiling_only_falls():
    n = len(_files()) + 1  # + the index itself, matching the doc's own count
    assert n <= CEILING, (
        f"{n} files against the recorded ceiling of {CEILING}. The doc's own "
        "rule is ABSORB OR ARCHIVE, not accrete; if this growth is deliberate, "
        "raising CEILING here is the loud act it must be")
