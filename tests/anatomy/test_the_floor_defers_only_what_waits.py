"""Gate — the security floor's lanes, and the one thing they must never do.

Doctrine: docs/doctrine/security-floor.md.

The roadmap asked for "act on CRITICAL/HIGH, batch the rest to a release
boundary". Measured 2026-08-22, that rest is not one thing: of 45 pending rows
below HIGH, 15 are `version_bump` (a release moves pins, so a tag means
something) and 30 are not — 21 of those are `config_change`, blocked on nobody.
Deferring them to a tag relabels actionable work as upstream-gated.

So the lane is chosen by what a row is BLOCKED ON. What this gate pins is
narrow and deliberate:

  * the lanes stay disjoint and cover every pending row — a row that falls into
    no lane is invisible, which is the `unjudged` defect that cost this estate
    its first unattended night;
  * CRITICAL and HIGH are never deferrable, whatever they are blocked on;
  * and the floor never writes `status`.

That last one is structural rather than stylistic. `tools/rem-status.py` filters
`status == "pending"` strictly and `tools/discovery-scan.py` matches the literal
strings, so a `deferred` status would delete deferred rows from the tool
CLAUDE.md tells every reader to run first.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
QUEUE = REPO / "docs/llm/security/remediation-queue.json"
DOCTRINE = REPO / "docs/doctrine/security-floor.md"


@pytest.fixture(scope="module")
def rem():
    spec = importlib.util.spec_from_file_location(
        "rem_status_under_test", REPO / "tools" / "rem-status.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["rem_status_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def items() -> list[dict]:
    raw = json.loads(QUEUE.read_text(encoding="utf-8"))
    return raw["items"] if isinstance(raw, dict) and "items" in raw else raw


def test_the_lanes_partition_every_pending_row(rem, items):
    """Disjoint and total. A row in no lane is a row nobody schedules."""
    lane = rem.lanes(items)
    pending = [i for i in items if i.get("status") == "pending"]
    ids = [i.get("id") for group in lane.values() for i in group]
    assert len(ids) == len(set(ids)), "a row appears in two lanes"
    assert sorted(ids) == sorted(i.get("id") for i in pending), (
        "the lanes do not cover every pending row — a finding that belongs to no "
        "lane is one nothing selects, which is exactly how `unjudged` fell "
        "between propose and drive on the loop's first unattended night"
    )


def test_critical_and_high_are_never_deferrable(rem, items):
    lane = rem.lanes(items)
    for name in ("waits_for_a_tag", "waits_for_nobody"):
        offenders = [i.get("id") for i in lane[name]
                     if i.get("severity") in ("CRITICAL", "HIGH")]
        assert not offenders, (
            f"{offenders} are CRITICAL/HIGH and landed in the '{name}' lane. "
            f"Severity picks what must be noticed now; being blocked on nothing "
            f"never makes a CRITICAL wait."
        )


def test_the_floor_never_writes_status(rem):
    """The reader may read `status`; it may not be a route to changing one."""
    src = (REPO / "tools" / "rem-status.py").read_text(encoding="utf-8")
    for forbidden in ('"deferred"', "'deferred'", "status\"] =", "status'] ="):
        assert forbidden not in src, (
            f"rem-status.py contains {forbidden!r}. A deferral must live beside "
            f"`status`, never in it: rem-status filters `status == 'pending'` "
            f"strictly and discovery-scan matches the literal strings, so a new "
            f"status value deletes deferred rows from both."
        )


def test_the_tag_lane_holds_only_what_a_tag_moves(rem, items):
    """A release moves pins. Anything else in that lane is mislabelled."""
    lane = rem.lanes(items)
    wrong = [(i.get("id"), i.get("remediation_type")) for i in lane["waits_for_a_tag"]
             if i.get("remediation_type") not in rem.WAITS_FOR_A_TAG]
    assert not wrong, f"rows in the tag lane that a tag does not move: {wrong}"


def test_the_doctrine_records_what_was_refused(rem):
    """The refusals are the durable half and must not quietly disappear.

    Four designs were panelled; three of their central mechanisms were refused
    on evidence. If a later reader finds only the surviving rule, they will
    propose the refused ones again — one of which was disproved by building it.
    """
    assert DOCTRINE.exists(), f"the floor's doctrine is missing: {DOCTRINE}"
    text = DOCTRINE.read_text(encoding="utf-8")
    for needle in ("refused", "reachability", "phase", "CVSS"):
        assert needle in text, (
            f"docs/doctrine/security-floor.md no longer records {needle!r} among "
            f"the refusals"
        )
