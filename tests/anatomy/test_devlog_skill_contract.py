"""Anatomy CI gate — /devlog skill contract.

The skill is how agent sessions read/write the devlog instead of dozens of
.md files; pin that it exists, declares itself, and routes every WP write
through the audited helper (docs/devlog/README.md § Audit doctrine).
"""
from __future__ import annotations

import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
SKILL = REPO / ".claude/skills/devlog/SKILL.md"


def test_skill_exists_with_frontmatter():
    assert SKILL.is_file(), ".claude/skills/devlog/SKILL.md missing"
    text = SKILL.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    fm = text.split("---\n", 2)[1]
    assert "name: devlog" in fm
    assert "description:" in fm


def test_skill_references_the_audited_toolchain():
    text = SKILL.read_text(encoding="utf-8")
    for ref in ("tools/devlog-post.py", "tools/devlog-compile.py",
                "docs/devlog/README.md", "tools/devlog-release.sh"):
        assert ref in text, f"skill must reference {ref}"
    assert "never raw curl" in text, "audit rule (helper-only writes) missing"


def test_skill_covers_all_modes():
    text = SKILL.read_text(encoding="utf-8")
    for mode in ("## read", "## new", "## post", "## release"):
        assert mode in text, f"skill missing mode section {mode}"
