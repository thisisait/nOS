"""Anatomy gate: `(int)` of an AST param was always 1, and nothing could fail.

MEASURED 2026-08-11, live, while testing the newly-threaded pipeline:

    get(tax:01) | map(tax:01) | rank(by=physics, limit=3)   ->  rank rows=1

Three was asked for and one arrived. `cortex-lang.ts` emits every parameter as an
OBJECT — `{value, defaulted, span}` — because the span is what a validator error
points at. Handlers read the map directly and cast:

    $limit = (int) ($stage->params['limit'] ?? 20);

`(int)` of a non-empty PHP array is **1**. So every `limit=` ever written in a
chain meant one row, `threshold=70` meant one percent, and no error was raised at
any layer: the grammar accepted it, the validator typed it, the handler cast it,
and the answer came back looking like a small result set.

WHY THIS OUTRANKS THE BUG ITSELF. `GetHandler` was the one handler that had
shipped WORKING, and it carried this since the day it landed —
`get(tax:01, limit=50)` returned a single row and read as a node with one child.
The verbs that were late-bound were, in this one respect, safer than the verb
that ran. A cast that cannot fail over a shape nobody checked is how a value
silently becomes 1 for months.

WHAT IS PINNED: that handlers go through `ResolvedStage::param()`, which unwraps
once, in one place. A gate on the VALUE (limit really is 3) would need a live
KEAP; a gate on the ACCESS PATH is offline and catches the next handler written
by someone who reaches into `$stage->params` out of habit.
"""

from __future__ import annotations

import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
HANDLERS = REPO / "files/anatomy/wing/app/Cortex/Handler"
STAGE = REPO / "files/anatomy/wing/app/Cortex/ResolvedStage.php"
GRAMMAR = REPO / "files/anatomy/cortex/server/cortex-lang.ts"


def test_the_grammar_still_emits_params_as_objects() -> None:
    """The premise. If params became scalars, this whole gate is obsolete."""
    src = GRAMMAR.read_text(encoding="utf-8")
    assert re.search(r"params\[[^\]]+\]\s*=\s*\{\s*value:", src), (
        "cortex-lang no longer emits params as {value, …} objects. If they are "
        "scalars now, unwrapping is unnecessary and this gate should be deleted "
        "— but check every handler first, because they all unwrap."
    )


def test_resolved_stage_offers_one_unwrapping_accessor() -> None:
    src = STAGE.read_text(encoding="utf-8")
    assert "function param(" in src, (
        "ResolvedStage::param() is gone. It is the single place the "
        "{value, defaulted, span} envelope is opened; without it every handler "
        "opens it again, and the one that forgets casts an array to 1."
    )
    assert "'value'" in src, "param() no longer reads the `value` key"


@pytest.mark.parametrize("handler", sorted(p.name for p in HANDLERS.glob("*.php")))
def test_no_handler_reaches_into_the_raw_param_map(handler: str) -> None:
    """The access path, per handler, so the failure message names the file."""
    src = (HANDLERS / handler).read_text(encoding="utf-8")
    raw = re.findall(r"\$stage->params\[", src)
    assert not raw, (
        f"{handler} reads $stage->params[...] directly. That map holds "
        "{value, defaulted, span} objects, so casting an element gives 1 for "
        "(int), '1' for (string) and true for (bool) — silently, forever. Use "
        "$stage->param('key', $default)."
    )


def test_the_accessor_survives_both_shapes() -> None:
    """Unit-checks the unwrap by reading it, since PHP is not available here.

    Deliberately a source assertion rather than a php-shelling probe: this file
    runs in the Pytest CI job, which has PHP but no Wing, and the behaviour that
    matters is one branch. What it must do is return the inner `value` for an
    envelope and the datum itself for a bare scalar — the second because the
    executor's own tests construct stages by hand with flat params.
    """
    src = STAGE.read_text(encoding="utf-8")
    body = src[src.index("function param("):]
    body = body[: body.index("\n    }")]
    assert "is_array" in body, (
        "param() no longer distinguishes an envelope from a scalar. Handed a "
        "hand-built flat param it would return null, and every offline test "
        "that constructs a ResolvedStage would silently take defaults."
    )
    assert "array_key_exists" in body or "isset" in body, (
        "param() does not check for the `value` key before reading it"
    )
