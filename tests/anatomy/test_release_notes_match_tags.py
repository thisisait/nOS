"""Anatomy gate: a tagged release's notes are not a draft.

MEASURED 2026-10-21: tag v0.17-beta (d195ed76, 2026-10-17) existed on origin
while RELEASE.md still headed its section "— DRAFT". A reader of the notes could
not tell what shipped from what was planned. Two rules, read from git tags and
RELEASE.md headings: a section whose tag exists carries no DRAFT marker, and the
newest tagged section names its tag commit (8-char prefix).

Tags are read from origin (`git ls-remote`), not the local tag list: CI checks
out shallow with no tags, a local tag may never have been pushed, and a clone
may not have fetched the newest one.
"""
import re
import subprocess
from pathlib import Path

import pytest
from _environment_contract import declared_tools

ROOT = Path(__file__).resolve().parents[2]
HEADING = re.compile(r"^## (v\d+\.\d+(?:\.\d+)?(?:-[\w.]+)?)\b(.*)$", re.M)


def _unknown(why):
    """An environment that declares git (CI) must answer; elsewhere UNKNOWN."""
    if "git" in declared_tools():
        pytest.fail(f"{why}, and NOS_TEST_PROVIDES declares git: this gate must run here")
    pytest.skip(f"{why}: UNKNOWN, not green")


def _tags():
    """{tag: commit sha} as origin holds them; annotated tags peeled."""
    try:
        out = subprocess.run(["git", "ls-remote", "--tags", "origin", "v*"], cwd=ROOT,
                             capture_output=True, text=True, check=True, timeout=60).stdout
    except (subprocess.SubprocessError, OSError) as exc:
        _unknown(f"origin tags unreadable ({type(exc).__name__})")
    tags = {}
    for line in out.splitlines():
        sha, ref = line.split("\t")
        name = ref.removeprefix("refs/tags/")
        if name.endswith("^{}"):
            tags[name[:-3]] = sha
        else:
            tags.setdefault(name, sha)
    return tags


def _sections():
    text = (ROOT / "RELEASE.md").read_text(encoding="utf-8")
    heads = list(HEADING.finditer(text))
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        yield m.group(1), m.group(2), text[m.start():end]


def _tagged():
    tags = _tags()
    if not tags:
        _unknown("origin lists no v* tags")
    return [(v, h, body, tags[v]) for v, h, body in _sections() if v in tags]


def test_a_tagged_section_is_not_a_draft():
    drafts = [v for v, head, _, _ in _tagged() if "DRAFT" in head]
    assert not drafts, f"tagged but RELEASE.md still says DRAFT: {drafts}"


def test_the_newest_tagged_section_names_its_tag_commit():
    tagged = _tagged()
    assert tagged, "no RELEASE.md section matches an existing tag"
    version, _, body, sha = tagged[0]  # RELEASE.md is newest-first
    assert sha[:8] in body, f"{version} section does not name its tag commit {sha[:8]}"
