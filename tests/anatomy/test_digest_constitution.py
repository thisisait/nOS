"""The digest constitution is ENFORCED, not prose.

state/digest-constitution.yml lists the digest organ's invariants, each paired
with the judge that enforces it. This gate refuses the file if a rule marked
`enforced` names a judge or gate that does not exist — so a constitutional rule
nothing enforces cannot masquerade as enforced. A `pending` rule is honest: it
must NOT claim a judge (either it's enforced by real code, or it says it isn't
yet and names the row that will build it).
"""
import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
CONSTITUTION = REPO / "state" / "digest-constitution.yml"


def _invariants():
    return yaml.safe_load(CONSTITUTION.read_text())["invariants"]


def test_every_rule_has_a_known_status_and_unique_id():
    inv = _invariants()
    ids = [r["id"] for r in inv]
    assert len(ids) == len(set(ids)), f"duplicate invariant id(s): {ids}"
    for r in inv:
        assert r.get("status") in ("enforced", "pending"), f"{r['id']}: bad status {r.get('status')!r}"
        assert r.get("rule", "").strip(), f"{r['id']}: empty rule text"


def test_enforced_rules_name_a_judge_that_exists():
    """The load-bearing check: enforced ⇒ the judge symbol and the gate file
    are really present. A rule with no real enforcer is a failing gate, here."""
    for r in _invariants():
        if r["status"] != "enforced":
            continue
        judge = r.get("judge", "")
        assert "::" in judge, f"{r['id']}: enforced rule needs a judge path::symbol, got {judge!r}"
        path, symbol = judge.split("::", 1)
        src = REPO / path
        assert src.exists(), f"{r['id']}: judge file {path} does not exist"
        text = src.read_text()
        assert f"def {symbol}" in text, f"{r['id']}: judge {symbol} not defined in {path}"
        gate = REPO / r.get("gate", "")
        assert r.get("gate") and gate.exists(), f"{r['id']}: gate {r.get('gate')!r} does not exist"


def test_pending_rules_do_not_claim_enforcement():
    """A pending rule must not name a judge/gate (that would be a lie); it must
    name the row that will build its judge, so the gap is tracked, not hidden."""
    for r in _invariants():
        if r["status"] != "pending":
            continue
        assert not r.get("judge") and not r.get("gate"), (
            f"{r['id']}: pending rule claims a judge/gate — either enforce it or leave both empty")
        assert r.get("builds_with"), f"{r['id']}: pending rule must name builds_with (the row that closes it)"
