"""A notify body is the observation, not the prompt that asked for one.

S2's 14-night ceiling used to fire with body
'Report whatever the harness has, with its denominator.' — the instruction,
the same family as a success marker written by the attempting code. This test
is the reader of the body string: it evaluates the notify() body expression
against a synthetic ledger and checks nights, disagreements, streak, and the
denominator. It does not claim the corpus is healthy.
"""
from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "files" / "anatomy" / "scripts" / "cortex-corpus-diff.py"

INSTRUCTION = "Report whatever the harness has, with its denominator."


def _load():
    spec = importlib.util.spec_from_file_location("cortex_corpus_diff", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["cortex_corpus_diff"] = mod
    spec.loader.exec_module(mod)
    return mod


def _notify_call(title_needle: str) -> ast.Call:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, "id", None) != "notify":
            continue
        if len(node.args) < 4:
            continue
        if title_needle in ast.unparse(node.args[2]):
            return node
    raise AssertionError(f"no notify() titled {title_needle!r}")


def _body(mod, title_needle: str, state: dict, report: dict) -> str:
    expr = _notify_call(title_needle).args[3]
    wrapped = ast.Expression(body=expr)
    ast.fix_missing_locations(wrapped)
    return eval(  # noqa: S307 — reading our own notify body expression
        compile(wrapped, str(SCRIPT), "eval"),
        {**vars(mod), "state": state, "report": report},
    )


def _assert_observation(body: str, state: dict, denom: int) -> None:
    assert body != INSTRUCTION
    assert str(len(state["nights"])) in body
    assert str(state["disagreements"]) in body
    assert str(state["agreeStreak"]) in body
    assert str(denom) in body
    assert "denominator" in body.lower()
    assert "healthy" not in body.lower()


def test_fourteen_night_and_disagreement_notify_bodies_are_harness_facts():
    mod = _load()
    denom = 41
    report = {"realUserDocs": denom}

    ceiling_state = {
        "nights": [{}] * mod.NIGHT_CEILING,
        "agreeStreak": 0,
        "disagreements": 1,
    }
    disagree_state = {
        "nights": [{}] * 5,
        "agreeStreak": 0,
        "disagreements": mod.DISAGREEMENTS_ALLOWED,
    }

    ceiling = _body(mod, "ceiling reached", ceiling_state, report)
    disagree = _body(mod, "disagreeing nights", disagree_state, report)
    _assert_observation(ceiling, ceiling_state, denom)
    _assert_observation(disagree, disagree_state, denom)
