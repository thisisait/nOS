"""Anatomy gate — the levels body.py and body-plan-gen.py walk are the lexicon's.

WHY (repo-body-plan row body-plan-levels-complete, 2026-10-07). Both tools held
their own tuple of levels. After I-12 the lexicon gained `heartbeat` as a
cross-level word with a graph kind; a tuple that did not follow would draw
the heartbeat as plumbing and read as complete. The lexicon is the one source
(ssot/doctrine/body-plan.md §1): the ladder is `order` up to `cross`, and a
cross word is a level exactly when it names a graph kind.

Imports both tools and compares their constants to the lexicon; reads no prose.
"""
from __future__ import annotations

import importlib.util
import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
LEXICON = REPO / "state" / "genome" / "lexicon.yml"


def _mod(name: str):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), REPO / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _lexicon_levels() -> tuple[tuple[str, ...], tuple[str, ...]]:
    doc = yaml.safe_load(LEXICON.read_text(encoding="utf-8"))
    order = doc["order"]
    ladder = tuple(order[: order.index("cross")])
    systems = tuple(w for w, v in doc["words"].items()
                    if v.get("level") == "cross"
                    and any("graph_kind" in r for r in v.get("names") or []))
    return ladder, systems


def test_body_plan_gen_levels_are_the_lexicon():
    ladder, systems = _lexicon_levels()
    gen = _mod("body-plan-gen")
    assert tuple(gen.LADDER) == ladder, f"body-plan-gen LADDER {gen.LADDER} != lexicon {ladder}"
    assert tuple(gen.SYSTEMS) == systems, f"body-plan-gen SYSTEMS {gen.SYSTEMS} != lexicon {systems}"
    assert tuple(gen.ALL_LEVELS) == ladder + systems + ("internal",)


def test_body_py_levels_are_the_lexicon():
    ladder, systems = _lexicon_levels()
    body = _mod("body")
    assert tuple(body.LEVELS) == ladder + systems, (
        f"body.py LEVELS {body.LEVELS} != lexicon {ladder + systems}")
