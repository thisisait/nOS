"""Every stage of a cortex chain shares one action id.

MEASURED 2026-08-30 against the live ledger, and it is a correction of a claim
this repo made the day before:

    404 cortex_stage_finish events
    stage `index` runs 0,1,2,3,4,5,6      <- pipelines up to seven stages long
    404 distinct actor_action_ids, each carrying exactly ONE stage

`CortexExecutorPresenter` minted `'cx-' . bin2hex(random_bytes(10))` INSIDE the
`foreach ($stages …)` loop, so no two stages of one chain ever shared a key.
`CortexContext`'s own docblock promised the opposite — *"a single SELECT …
WHERE actor_action_id = ? reconstructs"* — and had said so since it was written.

WHAT THAT COST, which is the reason this file exists rather than a one-line fix.
On 2026-08-29 a Grafana panel was built that groups stage events by
`actor_action_id` and counts them. It reported **"all 390 chains are a single
stage — the typed pipeline IR has never executed a pipeline"**, that sentence
went into a dashboard, a roadmap row and a report to the operator, and every
word of it was an artefact of the broken key. The executor had run hundreds of
pipelines. A reader that groups by a key nobody sets correctly does not measure
the world; it measures the bug.

So the gate asserts the property the panel depends on, at the only place that
can guarantee it: the id is minted before the loop, once.

Retro-verified 2026-08-30 by moving the mint back inside the loop.
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
EXEC = REPO / "files/anatomy/wing/app/Presenters/Api/CortexExecutorPresenter.php"
CTX = REPO / "files/anatomy/wing/app/Cortex/CortexContext.php"


def _execute_body() -> str:
    src = EXEC.read_text(encoding="utf-8")
    start = src.index("$brokenAt = null;")
    end = src.index("foreach ($stages as $raw)", start)
    return src[start:end], src[end:]


def test_the_action_id_is_minted_before_the_loop() -> None:
    before, after = _execute_body()
    assert "$actionId = 'cx-'" in before, (
        "the chain's action id is not minted before `foreach ($stages …)`. If it "
        "is minted inside, every stage gets its own key, and a SELECT on the "
        "lineage key returns one row however long the chain is — which is how "
        "a seven-stage pipeline came to be reported as never having run.")
    loop = after[:after.index("\n        }")] if "\n        }" in after else after
    assert "$actionId = 'cx-'" not in loop, (
        "the action id is minted inside the stage loop as well — one of the two "
        "wins at runtime and a reader cannot tell which")


def test_the_index_still_distinguishes_the_stages() -> None:
    """Sharing the id is only safe because `index` keeps the stages apart. Drop
    it and the chain becomes an unordered bag of rows with one key."""
    # In the AUDIT PAYLOADS specifically. A first draft matched the substring
    # anywhere and stayed green when both audit calls lost it, because
    # `$brokenAt ??= ['index' => $stage->index …]` carries the same text.
    src = EXEC.read_text(encoding="utf-8")
    # The two STAGE audits only. A third `audit(` call exists at chain level
    # and has no stage to index — requiring it too made the gate red on correct
    # code, which is the fastest way to get a gate deleted.
    audits = [c for c in re.findall(r"\$this->audit\((.*?)\n\s*\]\);", src, re.S)
              if "cortex_stage_" in c]
    assert len(audits) == 2, (
        f"expected exactly the begin and finish stage audits, found {len(audits)}")
    for call in audits:
        assert "'index' => $stage->index" in call, (
            "a stage audit no longer carries `index`; with a shared action id "
            "that is the only thing saying which stage is which, and in what "
            "order:\n" + call[:200])


def test_the_contract_says_chain_not_stage() -> None:
    """The docblock promised chain-wide reconstruction while the code delivered
    per-stage ids for the life of the file. Whichever is edited next, they have
    to move together."""
    doc = CTX.read_text(encoding="utf-8")
    assert "ONE PER CHAIN" in doc, (
        "CortexContext no longer states that the action id spans the chain — "
        "the sentence that was true of the intent and false of the code")
    assert "one per stage, minted before the" not in doc, (
        "the old per-stage promise is back in the docblock")
