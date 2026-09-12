"""The moderation-drain PLAN logic (moderation-drain-loop, offline core).

plan_drain classifies proposed briefs into retarget (dead) / human-review
(nos.* + overwrite) / per-domain batchable fills with a deterministic spot-check.
It NEVER approves — it drafts the batch the operator judges. Pure, so tested here;
the live reader + apply + backport are the operator's, pin-gated.
"""
import importlib.util
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]


def _md():
    spec = importlib.util.spec_from_file_location("moderation_drain", REPO / "tools" / "moderation-drain.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


MD = _md()

ITEMS = (
    [{"id": "dead1", "domain": "04", "is_fill": True, "target_alive": False, "is_nos": False}]      # dead → retarget
    + [{"id": "nos1", "domain": "nos", "is_fill": True, "target_alive": True, "is_nos": True}]        # nos.* → human
    + [{"id": "over1", "domain": "04", "is_fill": False, "target_alive": True, "is_nos": False}]      # overwrite → human
    + [{"id": f"f04-{n:02}", "domain": "04", "is_fill": True, "target_alive": True, "is_nos": False} for n in range(20)]
    + [{"id": f"f05-{n}", "domain": "05", "is_fill": True, "target_alive": True, "is_nos": False} for n in range(5)]
)


def test_dead_targets_go_to_retarget_and_nothing_else_does():
    plan = MD.plan_drain(ITEMS)
    assert plan["retarget"] == ["dead1"]


def test_nos_and_overwrite_go_to_human_review():
    plan = MD.plan_drain(ITEMS)
    assert plan["human_review"] == ["nos1", "over1"]          # sorted; a fill never lands here


def test_fills_batch_per_domain_with_a_deterministic_spot_check():
    plan = MD.plan_drain(ITEMS)                               # threshold 0.9, sample 0.1
    d04 = plan["domains"]["04"]
    assert d04["total"] == 20
    assert d04["sample"] == ["f04-00", "f04-01"]              # ceil(0.1*20)=2, sorted, first k
    assert d04["min_pass"] == 2                               # ceil(0.9*2)
    assert len(d04["batch_candidates"]) == 18 and "f04-00" not in d04["batch_candidates"]
    d05 = plan["domains"]["05"]
    assert d05["total"] == 5 and d05["sample"] == ["f05-0"] and d05["min_pass"] == 1
    assert len(d05["batch_candidates"]) == 4


def test_nothing_is_auto_approved():
    # the plan has no "approve" list — approving is the operator's, per contract.
    plan = MD.plan_drain(ITEMS)
    assert set(plan) == {"retarget", "human_review", "domains"}
