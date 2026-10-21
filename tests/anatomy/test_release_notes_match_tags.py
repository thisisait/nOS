"""Anatomy gate: a tagged release's notes are not a draft.

MEASURED 2026-10-21: tag v0.17-beta (d195ed76, 2026-10-17) existed on origin
while RELEASE.md still headed its section "— DRAFT". A reader of the notes could
not tell what shipped from what was planned. Two rules, read from git tags and
RELEASE.md headings: a section whose tag exists carries no DRAFT marker, and the
newest tagged section names its tag commit (8-char prefix).
"""
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HEADING = re.compile(r"^## (v\d+\.\d+(?:\.\d+)?(?:-[\w.]+)?)\b(.*)$", re.M)


def _tags():
    out = subprocess.run(["git", "tag", "--list", "v*"], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout
    return set(out.split())


def _sections():
    text = (ROOT / "RELEASE.md").read_text(encoding="utf-8")
    heads = list(HEADING.finditer(text))
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        yield m.group(1), m.group(2), text[m.start():end]


def _tagged():
    tags = _tags()
    if not tags:
        pytest.skip("no git tags in this checkout (shallow clone): UNKNOWN, not green")
    return [(v, h, body) for v, h, body in _sections() if v in tags]


def test_a_tagged_section_is_not_a_draft():
    drafts = [v for v, head, _ in _tagged() if "DRAFT" in head]
    assert not drafts, f"tagged but RELEASE.md still says DRAFT: {drafts}"


def test_the_newest_tagged_section_names_its_tag_commit():
    tagged = _tagged()
    assert tagged, "no RELEASE.md section matches an existing tag"
    version, _, body = tagged[0]  # RELEASE.md is newest-first
    sha = subprocess.run(["git", "rev-list", "-n1", version], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout.strip()
    assert sha[:8] in body, f"{version} section does not name its tag commit {sha[:8]}"
