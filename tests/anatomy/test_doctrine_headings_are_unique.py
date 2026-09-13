"""Anatomy gate — a doctrine heading is an address, so it cannot collide.

Subject: docs/doctrine/ssot.md (PROPOSED) §7. The citation indexer
(`tools/doctrine-cite.py` `index_doc`) last-write-wins on a repeated section
number, so two `## 9` headings silently become one address. This gate pins
docs/doctrine/*.md. A duplicate number outside that tree is not a nos-sot
address; docs/workflow-standard.md still carries two headings numbered 9.

Retro-red: the checker fails a synthetic duplicate (title and number) and
fails the live companion on number `9`. A check that cannot fail on a broken
input pins nothing.
"""
from __future__ import annotations

import importlib.util
import re
import sys
from collections import Counter
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
DOCTRINE = REPO / "docs" / "doctrine"
WORKFLOW_STANDARD = REPO / "docs" / "workflow-standard.md"

ATX = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.M)


def _tool():
    spec = importlib.util.spec_from_file_location(
        "doctrine_cite", REPO / "tools" / "doctrine-cite.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["doctrine_cite"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def tool():
    return _tool()


def _atx_titles(text: str) -> list[str]:
    return [m.group(2) for m in ATX.finditer(text)]


def _numbered_ids(tool, text: str) -> list[str]:
    ids = []
    for line in text.splitlines():
        m = tool.RE_HEAD_NUM.match(line)
        if m:
            ids.append(tool._norm_section(m.group(1)))
    return ids


def _dups(items: list[str]) -> dict[str, int]:
    return {k: n for k, n in Counter(items).items() if n > 1}


def test_a_duplicate_title_fails():
    text = "# T\n## Same\n## Same\n"
    assert _dups(_atx_titles(text)) == {"Same": 2}


def test_a_duplicate_section_number_fails(tool):
    """The workflow-standard shape: two different titles, one number."""
    text = "# T\n## 9. Recursion\n## 9. The checklist\n"
    assert _dups(_numbered_ids(tool, text)) == {"9": 2}


def test_every_doctrine_file_has_unique_headings(tool):
    collisions = []
    trees = [DOCTRINE, REPO / "ssot" / "doctrine"]
    for tree in trees:
        if not tree.is_dir():
            continue
        for path in sorted(tree.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            rel = path.relative_to(REPO)
            title_dups = _dups(_atx_titles(text))
            number_dups = _dups(_numbered_ids(tool, text))
            if title_dups:
                collisions.append(f"{rel} duplicate titles: {title_dups}")
            if number_dups:
                collisions.append(f"{rel} duplicate section numbers: {number_dups}")
    assert not collisions, "doctrine heading collisions:\n  " + "\n  ".join(collisions)


def test_workflow_standard_section_nine_is_a_named_collision(tool):
    """Companion, not constitution. If the two §9 headings are repaired,
    delete this test. File on this line: docs/workflow-standard.md.
    """
    text = WORKFLOW_STANDARD.read_text(encoding="utf-8")
    dups = _dups(_numbered_ids(tool, text))
    assert dups.get("9") == 2, (
        "docs/workflow-standard.md no longer has two headings numbered 9 — "
        "remove this test"
    )
