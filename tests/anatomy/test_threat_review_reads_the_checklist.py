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


def test_coderabbit_names_as_many_sections_as_the_checklist_has():
    """Review 2026-10-04: §6 landed, the config still said "all five sections"."""
    cfg = yaml.safe_load((REPO / ".coderabbit.yaml").read_text())
    text = " ".join(p["instructions"] for p in cfg["reviews"]["path_instructions"])
    words = {"five": 5, "six": 6, "seven": 7, "eight": 8}
    said = [n for w, n in words.items() if f"all {w}" in text]
    heads = re.findall(r"^## \d\.", (REPO / CHECKLIST).read_text(), re.M)
    assert said == [len(heads)], f"config says {said}, checklist has {len(heads)} sections"


def test_coderabbit_reviews_prs_into_master_and_dev():
    """PR #35 (2026-10-05): the bot skipped a dev→master PR as a non-default base."""
    auto = yaml.safe_load((REPO / ".coderabbit.yaml").read_text())["reviews"]["auto_review"]
    assert auto["enabled"] is True
    for branch in ("master", "dev"):
        assert any(re.fullmatch(p, branch) for p in auto["base_branches"]), branch


def test_coderabbit_config_matches_the_published_schema():
    """A misspelt key is silently ignored by the bot — so validate, offline,
    against the schema fetched 2026-10-05 (tests/fixtures). Re-fetch it when
    CodeRabbit adds a key we want."""
    import json

    import jsonschema
    schema = json.loads((REPO / "tests/fixtures/coderabbit-schema.v2.json").read_text())
    jsonschema.validate(yaml.safe_load((REPO / ".coderabbit.yaml").read_text()), schema)


def test_unknown_keys_are_refused_not_ignored():
    """Strict copy of the published schema: every object that lists its
    properties refuses others, at every depth (auto_review.base_brances too).
    The fixture stays byte-identical to what CodeRabbit publishes."""
    import json

    import jsonschema

    def strict(node):
        if isinstance(node, dict):
            if "properties" in node and "additionalProperties" not in node:
                node["additionalProperties"] = False
            for v in node.values():
                strict(v)
        elif isinstance(node, list):
            for v in node:
                strict(v)
        return node

    schema = strict(json.loads((REPO / "tests/fixtures/coderabbit-schema.v2.json").read_text()))
    jsonschema.validate(yaml.safe_load((REPO / ".coderabbit.yaml").read_text()), schema)
