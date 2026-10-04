"""Gate: the PR threat review reads the one checklist file, and only advises.

pr-threat-review-agent (operator 2026-10-04: CodeRabbit). The checklist is the
contract; an engine config that stops pointing at it reviews nothing we wrote.
"""
import datetime
import importlib.util
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


def test_the_checklist_has_its_six_sections():
    heads = re.findall(r"^## (\d)\.", (REPO / CHECKLIST).read_text(), re.M)
    assert heads == ["1", "2", "3", "4", "5", "6"]


def test_section_six_names_the_session_and_its_doctrine():
    text = (REPO / CHECKLIST).read_text()
    six = text.split("## 6.", 1)[1]
    assert "Session compromise" in six.splitlines()[0]
    assert "ssot/doctrine/session-threat-model.md" in six


def test_the_threat_model_carries_its_review_date_as_data():
    """The monthly review is front matter a reader can date, not a sentence."""
    text = (REPO / "ssot/doctrine/session-threat-model.md").read_text()
    front = yaml.safe_load(text.split("---", 2)[1])
    assert isinstance(front["last_reviewed"], datetime.date)
    assert front["review_every_days"] <= 31


def test_red_status_names_an_overdue_review(tmp_path):
    spec = importlib.util.spec_from_file_location("_red", REPO / "tools" / "red-status.py")
    red = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(red)
    (tmp_path / "late.md").write_text("---\nlast_reviewed: 2026-01-01\nreview_every_days: 31\n---\n# x\n")
    (tmp_path / "fresh.md").write_text("---\nlast_reviewed: 2099-01-01\nreview_every_days: 31\n---\n# y\n")
    (tmp_path / "plain.md").write_text("# no cadence\n")
    overdue = red.doctrine_reviews(tmp_path)
    assert [o["doc"] for o in overdue] == ["late.md"]
    assert red.reds({"doctrine_reviews": overdue})
