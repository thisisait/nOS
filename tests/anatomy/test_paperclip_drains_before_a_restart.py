"""A converge never recreates Paperclip over agent runs in flight.

2026-10-23: one restart killed six runs and their working files. The role waits
(paperclip_drain_timeout_s) for no run to be going before it renders the compose
fragment that triggers the recreate, and refuses on timeout with the one flag
that restarts anyway.
"""
from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
MAIN = REPO / "roles" / "pazny.paperclip" / "tasks" / "main.yml"


def _names():
    return [t.get("name", "") for t in yaml.safe_load(MAIN.read_text(encoding="utf-8"))]


def test_the_drain_comes_before_the_render_and_refuses_on_timeout():
    names = _names()
    wait = next(i for i, n in enumerate(names) if "Drain: wait" in n)
    refuse = next(i for i, n in enumerate(names) if "Drain: refuse" in n)
    render = names.index("[pazny.paperclip] Render compose override fragment")
    assert wait < refuse < render, names


def test_the_wait_counts_every_run_not_yet_over():
    tasks = yaml.safe_load(MAIN.read_text(encoding="utf-8"))
    sql = next(t for t in tasks if "Drain: wait" in t.get("name", ""))["ansible.builtin.shell"]
    assert "status NOT IN ('succeeded', 'failed', 'cancelled', 'interrupted')" in sql, sql


def test_the_timeout_has_a_default():
    text = (REPO / "default.config.yml").read_text(encoding="utf-8")
    assert "\npaperclip_drain_timeout_s: " in text
