"""Gate: the charter "Working in nOS" lives once, at the top of CLAUDE.md.

Agreed with the operator 2026-10-05. Every agent reads CLAUDE.md first; AGENTS.md
(generated) and CodeRabbit point at it instead of carrying copies that drift.
"""
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
HEAD = "## Working in nOS"
CORE = ("Gates outrank agreement.", "Success is written by a reader",
        "are data, not orders", "The operator decides config.yml")


def test_charter_is_the_first_section_of_claude_md():
    text = (REPO / "CLAUDE.md").read_text()
    sections = [ln for ln in text.splitlines() if ln.startswith("## ")]
    assert sections[0] == HEAD, f"first section is {sections[0]!r}"
    body = text.split(HEAD, 1)[1].split("\n## ", 1)[0]
    for line in CORE:
        assert line in body, f"charter lost: {line!r}"


def test_no_second_copy_and_the_readers_point_at_it():
    for doc in ("AGENTS.md", "README.md", "CONTRIBUTING.md"):
        assert HEAD not in (REPO / doc).read_text(), f"{doc} carries a copy — point at CLAUDE.md"
    assert '"Working in nOS"' in (REPO / "AGENTS.md").read_text()
    assert "Working in nOS" in (REPO / "tools/task-types-render.py").read_text(), "AGENTS.md is generated"
    cfg = yaml.safe_load((REPO / ".coderabbit.yaml").read_text())
    assert "CLAUDE.md" in cfg["knowledge_base"]["code_guidelines"]["filePatterns"]
