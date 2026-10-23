"""Anatomy gate — the wiring around a symbiont has its words: symbiosome, transporter.

WHY (roadmap row symbiosome-words, ruled 2026-10-23). A plugin.yml is the membrane
nOS builds around one hosted symbiont; each wiring block is one exchange across it.
The words name that without renaming a path; the plugin word points at its successor
until the rename row lands. `sanction` (cutting a cheating symbiont's supply) is
proposed only, so it must say so.
"""
from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
WORDS = yaml.safe_load((REPO / "state/genome/lexicon.yml").read_text(encoding="utf-8"))["words"]


def test_the_membrane_words_are_in_the_lexicon():
    for word in ("symbiosome", "transporter", "sanction"):
        assert word in WORDS, f"lexicon has no {word!r}"
        assert WORDS[word]["level"] == "cross", word
    assert not WORDS["symbiosome"].get("proposed") and not WORDS["transporter"].get("proposed")
    assert WORDS["sanction"].get("proposed") is True, "sanction is not ruled yet"


def test_plugin_points_at_its_successor():
    assert "symbiosome" in WORDS["plugin"]["means"]
    assert not WORDS["plugin"].get("retired"), "plugin is not retired in this row"


def test_the_docs_use_the_words():
    for rel in ("ssot/doctrine/body-plan.md", "files/anatomy/docs/plugin-wiring-capabilities.md"):
        text = (REPO / rel).read_text(encoding="utf-8")
        assert "symbiosome" in text and "transporter" in text, rel
