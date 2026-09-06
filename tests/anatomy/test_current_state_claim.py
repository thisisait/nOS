"""The claim engine refuses what it must: a held row, and an incapable agent.

The routing grammar is load-bearing only if the CLAIM enforces it — an agent
must not be able to take work the match says it cannot do (dtt-mcp-harness).
Pure-logic gate (the live door is integration); pins claimable() and may_claim().
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))


def _load(mod: str):
    spec = importlib.util.spec_from_file_location(mod, REPO / "tools" / f"{mod}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


cs = _load("current-state")

NOW = 1_800_000_000
CAPS = {"coder": "nos-work://local/agent:coder/repo/code-fix/*"}
ROW = {"slug": "r", "task_type": "code-fix", "where": "local", "kam": "repo"}


def test_claimable_respects_the_lease():
    assert cs.claimable({}, NOW)  # unclaimed
    assert cs.claimable({"claim": "agent:x", "lease_until": NOW - 1}, NOW)  # expired
    assert not cs.claimable({"claim": "agent:x", "lease_until": NOW + 999}, NOW)  # live lease
    assert not cs.claimable({"claim": "agent:x"}, NOW)  # held, no lease -> never auto-steal


def test_may_claim_enforces_capability():
    ok, _ = cs.may_claim(ROW, "agent:coder", CAPS)
    assert ok  # capable agent
    ok, why = cs.may_claim(ROW, "agent:someone-else", CAPS)
    assert not ok and "not capable" in why  # incapable agent refused
    ok, _ = cs.may_claim(ROW, "user:pazny", CAPS)
    assert ok  # a human may claim anything


def test_a_held_row_is_refused_even_to_a_capable_agent():
    held = {**ROW, "claim": "agent:coder", "lease_until": 9_999_999_999}  # year 2286
    # capable, but the row is validly held — still refused (no double-claim)
    ok, why = cs.may_claim(held, "agent:coder", CAPS)
    assert not ok and "already claimed" in why
