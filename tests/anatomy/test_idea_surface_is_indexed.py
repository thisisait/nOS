"""Anatomy CI gate — the idea surface is indexed, unique, and under its ratchet.

Fee 51 (audit 2026-09-02, verified 2026-09-03): the index promised a ceiling of
twenty in prose while 24 files existed, two numeric prefixes collided (11, 13)
and eight files were absent from the table — a constraint nobody gated, on the
surface that INVENTED the hidden-fee practice. active-work.md learned this
lesson (test_active_work_slim); the idea surface copied the ceiling, not the
gate.

The ceiling lives in ssot/INDEX.yml (realms.idea.ceiling) and is held by
tests/anatomy/test_docs_dirs_are_realms_or_frozen.py — one number, one gate.
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
IDEA = REPO / "docs" / "idea"

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

