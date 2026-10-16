"""Every row an agent's binder can serve it on is named in its committed Art-30 record.

WHY. A minimax-bound agent degrades to the hosted default (anthropic) when minimax is not
armed. effective_records() then appended Anthropic as "the agent's record does not name it":
the live /gdpr record and state/dpa-register.md disagreed. Armed-nothing and armed-everything
bound what the binders can pick; each serving row's processor must already be in the record.
"""
from __future__ import annotations

import pathlib

import yaml

from module_utils import nos_gdpr  # type: ignore  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[2]
BACKENDS = yaml.safe_load((REPO / "state/habitat/llm-backends.yml").read_text())["backends"]
FLAGS = {"install_thalamus": True, "install_loops": True, "install_wing": True}


def _unnamed():
    recs = [r for r in nos_gdpr.records_from_agents(REPO / "files/anatomy/agents") if r.get("binding")]
    bad = set()
    for armed in (set(), set(BACKENDS)):
        for rec in recs:
            name = rec["id"].removeprefix("agent_")
            cells = [None] + list(rec["binding"].get("backends_allowed") or [])
            for cell in cells:
                choices = {"armed": armed, "cells": {name: cell} if cell else {}, "agents_backend": "",
                           "posture": "standard", "flags": FLAGS}
                committed = [str(p.get("name") or "") for p in rec.get("processors") or []]
                live = nos_gdpr.effective_records([rec], choices, BACKENDS)[0]
                for row in filter(None, live["served_by"].split(", ")):
                    match = BACKENDS[row].get("processor_match") or ""
                    if match and not any(match in n for n in committed):
                        bad.add(f"{name}: serves on {row}, record lacks {match!r}")
    return sorted(bad)


def test_every_serving_row_is_named_in_the_record():
    assert _unnamed() == []
