"""The live Art-30 record names every row the person may pick for Iris, not only the host's.

WHY. W5 lets the person pick Iris's model per session among model.backends_allowed rows armed
here (thalamus serve, model_pick). A record that named only iris_backend would tell the DPO
nothing reaches Mistral while one click sends the turns there. So a cell's serving set is its
chosen row plus every allowed row that is armed, named by its record and the posture permits.
"""
from __future__ import annotations

import pathlib

import yaml

from module_utils import nos_gdpr  # type: ignore  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[2]
BACKENDS = yaml.safe_load((REPO / "state/habitat/llm-backends.yml").read_text())["backends"]
FLAGS = {"install_thalamus": True}


def _iris(**choices):
    base = {"armed": set(), "cells": {}, "agents_backend": "", "posture": "standard", "flags": FLAGS}
    recs = nos_gdpr.effective_records(nos_gdpr.records_from_agents(REPO / "files/anatomy/agents"), {**base, **choices}, BACKENDS)
    return next(r for r in recs if r["id"] == "agent_iris")


def _cell(posture):
    rec = {"id": "agent_c", "processors": [{"name": "Mistral AI SAS"}, {"name": "MiniMax"}], "transfers_outside_eu": 0,
           "binding": {"backend": "mistral-eu", "backends_allowed": ["mistral-eu", "minimax"], "primary": "openai-sonnet", "owner": None}}
    choices = {"armed": {"mistral-eu", "minimax"}, "cells": {}, "agents_backend": "", "posture": posture, "flags": {}}
    return nos_gdpr.effective_records([rec], choices, BACKENDS)[0]


def test_an_armed_row_the_person_may_pick_is_named():
    rec = _iris(armed={"ollama", "mistral-eu"}, cells={"iris": "ollama"})
    names = [p["name"] for p in rec["processors"]]
    assert "This host (on-device, Ollama)" in names and any("Mistral" in n for n in names), names
    assert rec["served_by"] == "ollama, mistral-eu" and rec["transfers_outside_eu"] == 0


def test_an_unarmed_row_is_not_pickable_so_not_named():
    rec = _iris(armed={"ollama"}, cells={"iris": "ollama"})
    assert [p["name"] for p in rec["processors"]] == ["This host (on-device, Ollama)"]


def test_a_non_eu_row_is_pickable_only_at_posture_none():
    held = _cell("standard")
    assert [p["name"] for p in held["processors"]] == ["Mistral AI SAS"] and held["transfers_outside_eu"] == 0
    loose = _cell("none")
    assert loose["served_by"] == "mistral-eu, minimax" and loose["transfers_outside_eu"] == 1
