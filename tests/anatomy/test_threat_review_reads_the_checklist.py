"""Gate: the PR threat review reads the one checklist file, and only advises.

pr-threat-review-agent (operator 2026-10-04: CodeRabbit). The checklist is the
contract; an engine config that stops pointing at it reviews nothing we wrote.
"""
import pathlib
import re

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
CHECKLIST = "docs/review/threat-checklist.md"


def test_coderabbit_reads_the_checklist_and_never_blocks():
    cfg = yaml.safe_load((REPO / ".coderabbit.yaml").read_text())
    assert CHECKLIST in cfg["knowledge_base"]["code_guidelines"]["filePatterns"]
    assert any(CHECKLIST in p["instructions"] for p in cfg["reviews"]["path_instructions"])
    assert cfg["reviews"]["request_changes_workflow"] is False


def test_the_checklist_has_its_five_sections():
    heads = re.findall(r"^## (\d)\.", (REPO / CHECKLIST).read_text(), re.M)
    assert heads == ["1", "2", "3", "4", "5"]
