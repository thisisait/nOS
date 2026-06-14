"""Anatomy gate — framework docs links point at files/anatomy/docs/, not docs/.

WHY: The six state/migration/upgrade framework guides — framework-overview,
framework-plan, migration-authoring, upgrade-recipes, coexistence-playbook,
wing-integration — were MOVED from docs/ to files/anatomy/docs/ in anatomy A1
(2026-05-03) per the operator-runbook-vs-agent-contract split rule
(CLAUDE.md line ~224). The move was committed but the link migration was
incomplete: README.md, TLDR.md, docs/restore-runbook.md, docs/roadmap-2026q2.md,
docs/anatomy.md and files/anatomy/migrations/README.md still pointed at the dead
docs/ paths, handing 404s to operators who click them in the primary entry
points (README/TLDR).

This gate pins the relocation: the six guides MUST exist at the new location,
MUST be absent from the old, and NO tracked markdown may reference the stale
`docs/<guide>.md` form. Trips if a guide regresses to docs/ or a new stale
reference is authored.
"""
from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]

# The six framework guides relocated in anatomy A1.
FRAMEWORK_DOCS = (
    "framework-overview.md",
    "framework-plan.md",
    "migration-authoring.md",
    "upgrade-recipes.md",
    "coexistence-playbook.md",
    "wing-integration.md",
)

NEW_DIR = REPO / "files" / "anatomy" / "docs"
OLD_DIR = REPO / "docs"

# Match a stale `docs/<guide>.md` reference but NOT the correct
# `files/anatomy/docs/<guide>.md` — the negative lookbehind rejects the
# files/anatomy/ prefix.
_STALE = re.compile(
    r"(?<!anatomy/)docs/(?:"
    + "|".join(re.escape(name[: -len(".md")]) for name in FRAMEWORK_DOCS)
    + r")\.md"
)

# Files we never want to lint (own histories / generated trees).
_SKIP_DIRS = {".git", ".ci-venv", "node_modules", "vendor"}


def test_framework_guides_live_at_new_location():
    """All six guides exist under files/anatomy/docs/ and none lingers in docs/."""
    for name in FRAMEWORK_DOCS:
        assert (NEW_DIR / name).is_file(), (
            f"{name} must live at files/anatomy/docs/{name} (anatomy A1 relocation)"
        )
        assert not (OLD_DIR / name).exists(), (
            f"docs/{name} must NOT exist — it was moved to files/anatomy/docs/ in "
            "anatomy A1; a stray copy means the relocation regressed"
        )


def _tracked_markdown() -> list[pathlib.Path]:
    out: list[pathlib.Path] = []
    for path in REPO.rglob("*.md"):
        if any(part in _SKIP_DIRS for part in path.relative_to(REPO).parts):
            continue
        out.append(path)
    return out


def test_no_stale_framework_doc_references():
    """No tracked markdown may reference the dead docs/<guide>.md paths."""
    offenders: dict[str, list[str]] = {}
    for path in _tracked_markdown():
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            if _STALE.search(line):
                rel = str(path.relative_to(REPO))
                offenders.setdefault(rel, []).append(f"  L{lineno}: {line.strip()}")
    assert not offenders, (
        "Stale framework-doc references found — these guides moved to "
        "files/anatomy/docs/ in anatomy A1; update the links:\n"
        + "\n".join(f"{f}\n" + "\n".join(lines) for f, lines in offenders.items())
    )
