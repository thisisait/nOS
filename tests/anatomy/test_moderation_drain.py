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


# ── prefilter operator draft (new heart; --json dumps this, not plan_drain) ──

PRE_ITEMS = (
    [{"id": "nos1", "nodeId": "nos.alpha"}]
    + [{"id": "fill1", "nodeId": "04.beta"}]
    + [{"id": "over1", "nodeId": "04.gamma", "overwrite": True}]
    + [{"id": "dead1", "nodeId": "04.delta", "dead-target": True}]
)


def test_prefilter_shape_unverified_and_apply_empty():
    draft = MD.draft_prefilter(PRE_ITEMS)
    assert draft["unverified"] is True
    assert draft["apply"] == []
    assert draft["reader"] == "GET /agent/v1/promotions?status=proposed"
    assert draft["queue_n"] == 4
    assert "approved" not in draft and "blessed" not in draft and "auto_approve" not in draft
    by_lab = {r["label"]: r for r in draft["ready_for_operator"]}
    assert [r["label"] for r in draft["ready_for_operator"]] == [
        "nos", "overwrite", "dead-target", "fill-ok",
    ]
    assert by_lab["nos"]["sort_key"] == 0 and by_lab["fill-ok"]["sort_key"] == 4
    assert "nos1" not in [e["id"] for e in draft["excluded"]]


def test_prefilter_nos_stays_in_draft_even_if_labels_say_low_match():
    labels = {
        "nos1": {"label": "low-match", "reason": "nope"},
        "fill1": {"label": "low-match", "reason": "weak"},
        "fill2": {"label": "attention", "reason": "odd"},
        "ghost": {"label": "low-match", "reason": "unknown id ignored"},
    }
    items = [
        {"id": "nos1", "nodeId": "nos.alpha"},
        {"id": "fill1", "nodeId": "04.beta"},
        {"id": "fill2", "nodeId": "04.gamma"},
        {"id": "fill3", "nodeId": "04.delta"},
    ]
    draft = MD.draft_prefilter(items, labels)
    assert [e["id"] for e in draft["excluded"]] == ["fill1"]
    assert draft["excluded"][0]["keap_status"] == "proposed"
    ready = {r["id"]: r["label"] for r in draft["ready_for_operator"]}
    assert ready["nos1"] == "nos"
    assert ready["fill2"] == "attention"
    assert ready["fill3"] == "fill-ok"
    assert "ghost" not in ready and "ghost" not in {e["id"] for e in draft["excluded"]}


def test_prefilter_skips_overwrite_dead_labels_when_fields_absent():
    draft = MD.draft_prefilter([{"id": "x", "nodeId": "04.only"}])
    assert draft["ready_for_operator"] == [
        {"id": "x", "label": "fill-ok", "sort_key": 4, "nodeId": "04.only"},
    ]


def test_tool_source_never_posts():
    """HEAD already never POSTed; a substring ban on 'decide'/'bulk' only
    forbade documenting the operator apply path. Pin the write instead."""
    src = (REPO / "tools" / "moderation-drain.py").read_text()
    assert "method=" not in src
    assert ".Request(" in src  # still GETs the promotions reader
