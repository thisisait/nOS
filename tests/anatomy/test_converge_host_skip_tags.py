"""Source-only skip-tags: CLT is brew's prerequisite, organs stay off the list.

converge-host-skip: a source bump still ran CLT/brew/cask/pip/npm. Forbidden
``main-fast.yml``. The profile is ``--skip-tags``, not a second playbook.
CLT had no tags, so it could not be skipped.

WHAT THIS PINS (YAML/text, no wet converge):
1. No ``main-fast.yml`` at repo root.
2. ``elliotweiser.osx-command-line-tools`` carries tag ``homebrew``.
3. The skip-list is the documented frozenset; organs+stacks are disjoint.
4. ``pazny.openclaw`` and ``pazny.ollama`` are tagged ``openclaw``, off the skip list.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
MAIN = REPO / "main.yml"

SKIP = frozenset({
    "homebrew", "mas", "dock", "apt", "packages", "python", "node", "nodejs",
    "bun", "go", "golang", "dotnet", "csharp", "extra-packages", "claude-cli",
    "sublime-text",
})
KEEP = frozenset({
    "openclaw", "anatomy", "stacks", "core", "pulse", "cortex",
})


def _tags(blob: str) -> set[str]:
    return {p.strip().strip("'\"") for p in blob.split(",") if p.strip()}


def test_no_main_fast_playbook():
    assert not (REPO / "main-fast.yml").exists(), (
        "main-fast.yml is forbidden; the profile is --skip-tags, not a "
        "second playbook (converge-host-skip)"
    )


def test_clt_is_tagged_homebrew():
    text = MAIN.read_text(encoding="utf-8")
    m = re.search(
        r"role:\s*elliotweiser\.osx-command-line-tools\n"
        r"(?:.*\n){0,8}?"
        r"\s+tags:\s*\[([^\]]+)\]",
        text,
    )
    assert m, (
        "elliotweiser.osx-command-line-tools has no tags — --skip-tags "
        "homebrew cannot skip CLT (converge-host-skip)"
    )
    tags = _tags(m.group(1))
    assert "homebrew" in tags, f"CLT tags {tags} do not include homebrew"


def test_skip_list_does_not_drop_organs_or_stacks():
    assert SKIP.isdisjoint(KEEP), (
        f"skip-list intersects organs/stacks: {SKIP & KEEP}"
    )


@pytest.mark.parametrize("role", ["pazny.openclaw", "pazny.ollama"])
def test_openclaw_stays_off_the_skip_list(role):
    """pazny.ollama carries the ollama pin since 2026-10-06 and keeps the openclaw tag."""
    text = MAIN.read_text(encoding="utf-8")
    m = re.search(
        rf"name:\s*{re.escape(role)}\n"
        r"(?:.*\n){0,16}?"
        r"\s+tags:\s*\[([^\]]+)\]",
        text,
    )
    assert m, f"{role} import_role has no tags"
    tags = _tags(m.group(1))
    assert "openclaw" in tags, f"{role} tags {tags} lost the openclaw tag"
    assert tags.isdisjoint(SKIP), (
        f"{role} tags {tags} intersect the host skip-list {tags & SKIP}; "
        "a source-only skip would drop the ollama pin"
    )
