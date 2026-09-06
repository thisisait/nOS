"""Every agent's derived nos-work:// capability address is sound.

The capability is a PROJECTION (docs/plans/routing-address.md §5, operator 2026-09-06):
tools/agent-capability.py derives each agent's address from its manifest. This
pins that the projection stays parseable under the reference grammar
(tools/nos_work_uri.py) and shaped as the planner will match it — so a manifest
edit that would emit a malformed address goes red offline, not at match time.
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


cap = _load("agent-capability")
uri = _load("nos_work_uri")


def test_every_emitted_capability_parses():
    emitted = {d["name"]: cap.capability(d) for d in cap._agents()}
    for name, addr in emitted.items():
        if addr is None:
            continue
        parsed = uri.parse(addr)  # raises on malformed
        assert parsed.who == {f"agent:{name}"}, f"{name}: WHO segment != its own name"


def test_task_types_flow_into_CO():
    by_name = {d["name"]: d for d in cap._agents()}
    conductor = cap.capability(by_name["conductor"])
    # conductor authors [investigate, review]; both must appear in CO.
    assert "investigate" in conductor and "review" in conductor
    parsed = uri.parse(conductor)
    assert parsed.co == {"investigate", "review"}


def test_a_toolless_local_agent_holds_no_scope():
    # ops-extract: no tools, local model → no external KAM → no routing address.
    by_name = {d["name"]: d for d in cap._agents()}
    assert cap.capability(by_name["ops-extract"]) is None


def test_the_deriver_check_passes():
    # The tool's own --check contract: all emitted addresses parse.
    assert cap.main.__module__  # module import sanity
    emitted = [a for a in (cap.capability(d) for d in cap._agents()) if a]
    assert emitted, "no capabilities emitted — the roster or deriver is broken"
    for addr in emitted:
        uri.parse(addr)
