"""Anatomy gate: a handler must not blame an upstream it never probed correctly.

THE CORRECTION THIS PINS, 2026-08-10. The cortex executor shipped with five of
seven verbs late-bound, and every one of them said the same thing: KEAP
publishes no read surface for it. That verdict came from a real probe — and the
probe tested the paths the DESIGN DOCUMENT named rather than the ones KEAP
serves. Re-probed against the running estate (127.0.0.1:8091, RO bearer):

    /agent/v1/taxonomy/node/:id   200   id, name, children, ancestors, childCount
    /agent/v1/taxonomy/search     200
    /agent/v1/search/semantic     200   with a `legs` block saying which ran
    /agent/v1/taxonomy            401   (no route at that exact path)

A 401 from the forward-auth catch-all on an unrouted path is byte-identical to a
scope refusal, which is how a careful measurement produced a false conclusion.

THE REAL BLOCKER, and the reason this gate is worth more than the five bodies:
read the registry's own summaries. `get` fetches the operand's record; `resolve`
resolves a term. Neither takes input. The other five are each defined over THE
INPUT — "project each item of the input", "keep the items of the input", "order
the input", "assign the input", "project the input into vector space". The two
verbs that execute are exactly the two needing no input; the five that do not
are exactly the five consuming it. The correlation is total.

`CortexExecutorPresenter` dispatches every stage independently and collects the
results side by side. Nothing carries stage N's rows into stage N+1 — the `|` in
the surface syntax does not pipe. So a verb defined over its input has no input.

This gate exists because the first diagnosis was wrong in the direction that
costs most: it pointed at someone else's repository. A blocker filed against an
upstream is a blocker nobody on this side will pick up.
"""

from __future__ import annotations

import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
HANDLERS = REPO / "files/anatomy/wing/app/Cortex/Handler"
CLIENT = REPO / "files/anatomy/wing/app/Model/KeapCortexClient.php"
PRESENTER = REPO / "files/anatomy/wing/app/Presenters/Api/CortexExecutorPresenter.php"

#: Routes measured 200 on 2026-08-10. A handler claiming KEAP publishes nothing
#: for a verb these serve is repeating the corrected mistake.
LIVE_ROUTES = (
    "/agent/v1/taxonomy/node/",
    "/agent/v1/taxonomy/search",
    "/agent/v1/search/semantic",
)

#: The false claim, in the shapes it was actually written in.
FALSE_CLAIMS = (
    re.compile(r"KEAP publishes no (?:node-fetch )?route", re.I),
    re.compile(r"which this deployment does not publish", re.I),
    re.compile(r"waiting on a route KEAP does not publish", re.I),
)


def _php_sources() -> list[pathlib.Path]:
    return sorted(HANDLERS.glob("*.php")) + [CLIENT]


def test_no_handler_still_claims_keap_publishes_nothing() -> None:
    offenders: list[str] = []
    for path in _php_sources():
        text = path.read_text(encoding="utf-8")
        for pattern in FALSE_CLAIMS:
            for match in pattern.finditer(text):
                line = text[: match.start()].count("\n") + 1
                offenders.append(f"{path.relative_to(REPO)}:{line}  {match.group(0)!r}")
    assert not offenders, (
        "a cortex handler blames KEAP for a route KEAP serves. The measured "
        f"surface is {', '.join(LIVE_ROUTES)}; the blocker is that this executor "
        "does not thread rows between stages. Blaming an upstream files the work "
        "in a repository nobody here will open:\n  " + "\n  ".join(offenders)
    )


def test_the_client_reaches_the_routes_that_exist() -> None:
    """The correction has to be in CODE, not only in a comment."""
    text = CLIENT.read_text(encoding="utf-8")
    for route in LIVE_ROUTES:
        assert route in text, (
            f"KeapCortexClient does not call {route}, which answers 200 to the RO "
            "bearer. A header that says the route exists while nothing calls it is "
            "the same defect one layer over."
        )


def test_get_actually_fetches_a_taxonomy_node() -> None:
    """`get(tax:…)` returned the AST's own resolution and called it the truth."""
    text = (HANDLERS / "GetHandler.php").read_text(encoding="utf-8")
    assert "taxonomyNode(" in text, (
        "GetHandler no longer fetches the node. It used to return only what the "
        "AST already carried, on the stated grounds that no fetch route existed — "
        "and that was the false claim."
    )
    assert "resolution only — KEAP node fetch did not answer" in text, (
        "the unreachable-KEAP fallback lost its label. An upstream that did not "
        "answer must not read like a node with no children."
    )


def test_late_bound_handlers_name_the_executor_not_the_upstream() -> None:
    late = [p for p in HANDLERS.glob("*.php")
            if "extends LateBoundHandler" in p.read_text(encoding="utf-8")]
    assert late, "no late-bound handlers left — delete this gate, or it has gone blind"
    base = (HANDLERS / "LateBoundHandler.php").read_text(encoding="utf-8")
    # Searched WITHOUT the leading "does": the sentence is split across a PHP
    # string concatenation, so the contiguous run is shorter than it reads.
    assert "thread rows between stages" in base, (
        "LateBoundHandler no longer names the real blocker. If stage threading "
        "landed, these verbs should have bodies rather than a new excuse."
    )
    for path in late:
        assert "awaiting()" in path.read_text(encoding="utf-8"), (
            f"{path.name} does not declare what it waits on"
        )


def test_the_executor_really_does_not_pipe() -> None:
    """Pin the mechanism, so the gate cannot outlive its reason.

    If this fails because rows ARE threaded now, that is the good outcome: the
    five verbs are unblocked and both this test and their bodies should change
    together.
    """
    text = PRESENTER.read_text(encoding="utf-8")
    dispatch = text[text.index("6 — dispatch"):]
    assert "$result = $this->opcodes->handler($stage->opcode)->execute($stage, $ctx);" in dispatch, (
        "the dispatch call changed shape — re-read whether stages now receive the "
        "previous stage's rows, and update LateBoundHandler's diagnosis with it."
    )
    # No previous-result variable reaches the next iteration.
    assert not re.search(r"\$prev|previousRows|\$carry", dispatch), (
        "something now carries rows between stages. That is the unblock — give "
        "map/filter/rank/classify a body and retire LateBoundHandler for them."
    )
