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

RESOLVED 2026-08-11, and the gate turned over with it. `CortexContext` now
carries the previous stage's rows and the executor threads them, so `|` pipes.
Four of the five verbs got bodies against routes that already answered — `map`
from node children, `classify` and `rank` from `/search/semantic`, and `filter`
from nothing at all, because it never needed an upstream. Only `embed` is still
late-bound, and for the one reason that was always genuinely upstream: KEAP has
`GET /embeddings/pending` and `POST /embeddings` but nothing that computes an
embedding for supplied text.

So the assertions below flipped from "the executor does not pipe" to "it does,
and a broken pipe propagates". The second half is the one to defend: a stage
that produced nothing must not hand its successor an empty world to answer
confidently over.
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


def test_only_embed_is_still_late_bound_and_for_an_upstream_reason() -> None:
    """The four that were blocked on US now have bodies; the one on THEM does not.

    Written as an exact set rather than "at least embed": a new late-bound
    handler appearing here would mean a verb was retired into a stub, and the
    whole point of this file is that a stub must name a blocker that is real.
    """
    late = {p.stem for p in HANDLERS.glob("*.php")
            if "extends LateBoundHandler" in p.read_text(encoding="utf-8")}
    assert late == {"EmbedHandler"}, (
        f"late-bound handlers are {sorted(late) or 'none'}; expected exactly "
        "{'EmbedHandler'}. map/filter/rank/classify were unblocked on 2026-08-11 "
        "when the executor began threading rows — if one is late-bound again, "
        "its stub must name a blocker that is true today, not the retired one."
    )

    base = (HANDLERS / "LateBoundHandler.php").read_text(encoding="utf-8")
    assert "awaiting()" in base, "LateBoundHandler no longer declares what it waits on"

    embed = (HANDLERS / "EmbedHandler.php").read_text(encoding="utf-8")
    assert "embeddings" in embed, (
        "EmbedHandler no longer names the route it is waiting on. It is the only "
        "verb whose blocker is genuinely upstream, and that is worth stating "
        "where someone will read it."
    )


def test_a_retired_diagnosis_does_not_survive_in_the_base_class() -> None:
    """The specific way this could rot: the sentence outliving the defect.

    `LateBoundHandler`'s body used to tell every caller that the executor does
    not thread rows. It does now. A stub still saying otherwise would send the
    next reader to fix something that was fixed, which is exactly the cost this
    file was opened to record — a blocker pointed at the wrong place.
    """
    base = (HANDLERS / "LateBoundHandler.php").read_text(encoding="utf-8")
    body = base[base.index("public function execute"):]
    # Searched WITHOUT the leading "does", for the reason the sibling test above
    # already records: the sentence is split across a PHP concatenation, so the
    # contiguous run is shorter than it reads. Written the obvious way this
    # assertion passed vacuously on its first run — against the very file whose
    # header warns about it.
    assert "not thread rows between stages yet" not in body, (
        "LateBoundHandler still tells callers the executor does not thread rows. "
        "It has since 2026-08-11. Update the message to name what `embed` is "
        "actually waiting on: a KEAP route that computes an embedding for "
        "supplied text."
    )


def test_the_executor_threads_rows_between_stages() -> None:
    """Pin the mechanism, in the direction it now runs.

    This asserted the opposite until 2026-08-11 and said so: "if this fails
    because rows ARE threaded now, that is the good outcome". It did, and this is
    the other side of that sentence.
    """
    text = PRESENTER.read_text(encoding="utf-8")
    dispatch = text[text.index("6 — dispatch"):]

    assert re.search(r"new CortexContext\([^)]*\$prev", dispatch), (
        "the executor no longer hands the previous stage's rows to the next "
        "context. Every verb defined over its input — map, filter, rank, "
        "classify — silently loses its input again, and the `|` in the surface "
        "syntax goes back to being punctuation."
    )
    assert re.search(r"\$prev\s*=\s*\$result->rows", dispatch), (
        "nothing assigns a stage's rows forward, so `$prev` is always empty."
    )


def test_a_broken_pipe_propagates_rather_than_emptying() -> None:
    """The half that is easy to lose and expensive to lose quietly.

    Three behaviours are possible when a stage produces nothing, and two of them
    lie. Carrying the previous rows through makes a dead stage look like a no-op.
    Substituting an empty list makes every downstream verb answer confidently
    over an empty world — `filter` returning zero rows reads identically whether
    it kept nothing or was never given anything. Only refusal is honest.
    """
    text = PRESENTER.read_text(encoding="utf-8")
    dispatch = text[text.index("6 — dispatch"):]

    assert "$brokenAt" in dispatch, (
        "the executor no longer tracks which stage broke the pipe, so a later "
        "stage cannot say why it has no input — it can only report zero rows, "
        "which is indistinguishable from a real empty answer."
    )
    assert "CortexStageResult::unavailable" in dispatch, (
        "a stage downstream of a break no longer returns a typed absence. It is "
        "answering over an empty world and calling that a result."
    )


def test_the_verbs_over_input_refuse_when_they_have_none() -> None:
    """Each unblocked handler must check, not assume.

    The executor's propagation covers a break MID-chain. It does not cover a
    chain that OPENS with a verb defined over input — `filter tax:x` as stage 0
    has no predecessor to break. Without a check in the handler that reads as a
    filter over nothing, returning nothing.
    """
    for name in ("MapHandler", "FilterHandler", "RankHandler", "ClassifyHandler"):
        src = (HANDLERS / f"{name}.php").read_text(encoding="utf-8")
        assert "hasInput()" in src, (
            f"{name} does not check whether it was given an input. As stage 0 of "
            "a chain it would operate on an empty list and report a confident "
            "nothing, which is the failure `CortexStageResult::unavailable` exists "
            "to keep distinguishable."
        )
