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


def _walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def test_the_verify_waits_for_the_pulls_it_judges():
    """The readiness verify fails on "not pulled"; a pull still running at that
    point is not a missing model. The play waits on the async jobs first."""
    pull = next(t for t in yaml.safe_load(TASKS.read_text()) if "ollama pull" in str(t.get("ansible.builtin.command", "")))
    tasks = [n for n in _walk(yaml.safe_load((REPO / "main.yml").read_text())) if "name" in n]
    names = [t["name"] for t in tasks]
    verify = names.index("[Verify] Every armed job has what it needs")
    waits = [i for i, t in enumerate(tasks)
             if "ansible.builtin.async_status" in t and pull["register"] in str(t.get("loop", ""))]
    assert waits and waits[0] < verify, "the verify judges a pull the play never waited for"
    w = tasks[waits[0]]
    assert "always" in w.get("tags", []), "--tags verify alone must wait too"
    assert int(w["retries"]) * int(w["delay"]) >= int(pull["async"]), "the wait gives up before the pull may"
    assert "failed_when" in w, "a failed pull is the verify's verdict, not the wait's"
