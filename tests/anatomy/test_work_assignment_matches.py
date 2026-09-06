"""The assignment side of dtt-routing-address: a currentState row projects to a
parseable nos-work:// address, and `assignment ⊆ capability` matches correctly.

Pure-function gate (offline): the live match report needs KEAP, but the shape of
an assignment address and the subset match are the definition, pinned here.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))


def _load(mod: str):
    spec = importlib.util.spec_from_file_location(mod, REPO / "tools" / f"{mod}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


wa = _load("work-assignment")
uri = _load("nos_work_uri")


def test_assignment_address_parses_and_who_is_star():
    row = {"slug": "a1", "task_type": "code-fix", "where": "local",
           "kam": "repo+dtt", "lease_until": "2026-09-20"}
    addr = wa.assignment_address(row)
    p = uri.parse(addr)
    assert p.who == {"*"}, "an assignment names no principal — WHO is *"
    assert p.co == {"code-fix"} and p.where == {"local"} and p.kam == {"repo", "dtt"}


def test_any_where_becomes_star():
    row = {"slug": "a2", "task_type": "review", "where": "any", "kam": "wing.read"}
    assert uri.parse(wa.assignment_address(row)).where == {"*"}


def test_missing_task_type_is_refused():
    with pytest.raises(ValueError):
        wa.assignment_address({"slug": "bad", "where": "local", "kam": "repo"})


def test_subset_match_is_correct():
    caps = {
        "coder": "nos-work://local/agent:coder/repo+dtt/code-fix+review/*",
        "designer": "nos-work://local/agent:designer/repo/design/*",
    }
    # a local repo code-fix → only the coder
    assert wa.capable_agents(
        {"slug": "r1", "task_type": "code-fix", "where": "local", "kam": "repo"}, caps
    ) == ["coder"]
    # a design task → only the designer
    assert wa.capable_agents(
        {"slug": "r2", "task_type": "design", "where": "local", "kam": "repo"}, caps
    ) == ["designer"]
    # needs dtt too → coder covers it, designer does not
    assert wa.capable_agents(
        {"slug": "r3", "task_type": "code-fix", "where": "local", "kam": "repo+dtt"}, caps
    ) == ["coder"]
    # ext-cloud placement neither can serve (both local)
    assert wa.capable_agents(
        {"slug": "r4", "task_type": "code-fix", "where": "ext-cloud", "kam": "repo"}, caps
    ) == []


def test_the_real_roster_capabilities_all_parse():
    caps = wa._capabilities()
    assert caps, "no agent capabilities derived — the roster or deriver is broken"
    for addr in caps.values():
        uri.parse(addr)
