"""A model pull never holds the converge.

2026-10-19, spark1: `ollama pull hermes3:8b` (4.7 GB at ~6 MB/s) blocked the
whole first converge for ~13 minutes while nothing after it needed the model.
The role now starts each missing pull with `async`/`poll: 0`; whether the model
ARRIVED is the verify play's question (tools/job_readiness.py --verify), not
the task's — success is written by a reader, not by the code that attempted it.
"""
from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
TASKS = REPO / "roles" / "pazny.ollama" / "tasks" / "main.yml"


def test_the_pull_is_fire_and_forget():
    pulls = [t for t in yaml.safe_load(TASKS.read_text()) if "ollama pull" in str(t.get("ansible.builtin.command", ""))]
    assert len(pulls) == 1
    t = pulls[0]
    assert t.get("poll") == 0, "a blocking pull holds the converge on the network"
    assert int(t.get("async", 0)) >= 3600, "the background pull must outlive a slow uplink"
    assert "timeout" not in t, "a task timeout would kill the pull it just started"
