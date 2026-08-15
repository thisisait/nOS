"""The persisted secret store must not outrank the operator's credentials.yml.

CLAUDE.md states the layering: `default.config.yml` → `default.credentials.yml`
→ `config.yml` → `credentials.yml`, later overriding earlier. `~/.nos/secrets.yml`
appears in that list nowhere — it is the runtime side-car, generated from the
layers, not a layer itself.

MEASURED 2026-08-15, the day it bit. The operator pasted a MiniMax API key into
`credentials.yml` and converged. `main.yml` loads credentials.yml in `pre_tasks`
and then loads the persisted store a few tasks later; both are `include_vars`,
which sit at the same precedence, so the LATER one wins. The store carried
`minimax_api_key` declared-and-EMPTY from an earlier run — the template writes
every name unconditionally, which is exactly what makes it "blank-safe" — so
the empty value shadowed the real one and the store was rewritten empty. The
groundwork doc calls pasting the key "the ONLY remaining step to arm the
backend"; it could not work on any host that had ever converged.

Replayed in order to be sure, rather than argued:

    after credentials.yml        126
    after ~/.nos/secrets.yml       0
    after the re-assert          126

BLAST RADIUS, measured not assumed: five of the operator's twelve keys also
live in the store and four AGREE byte-for-byte (the store was seeded from
them), so the re-assert restores one value and changes nothing else. The
divergence existed only for the key that had just been pasted — which is what
makes this class dangerous: it is invisible until the first time the operator
changes their mind, and then it silently ignores them.

This is the drift `docs/secret-lifecycle-doctrine.md` already names — a value
captured at bootstrap outranking the value the operator declares — arriving
one layer further out than the doc's own examples.

WHAT THIS PINS: order, in `main.yml`, by line number. Not that the re-assert
exists somewhere, but that it comes AFTER the store load; an include that
precedes it is the bug wearing the fix's name.
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
MAIN = REPO / "main.yml"

STORE_LOAD = "[Secrets] Load persisted secrets (if exists)"
REASSERT = "[Secrets] Re-assert operator credentials over the persisted store"


def _line_of(needle: str) -> int:
    for i, line in enumerate(MAIN.read_text(encoding="utf-8").splitlines(), 1):
        if needle in line:
            return i
    return -1


def test_both_tasks_still_exist():
    """Positive control — a renamed task would make the ordering check vacuous."""
    assert _line_of(STORE_LOAD) > 0, (
        f"the persisted-store load task is gone or renamed ({STORE_LOAD!r}); "
        "this gate can no longer see the thing it orders against."
    )
    assert _line_of(REASSERT) > 0, (
        f"the operator re-assert task is gone or renamed ({REASSERT!r}). "
        "Without it the store outranks credentials.yml again, and the symptom "
        "is a pasted secret that silently does nothing."
    )


def test_the_reassert_comes_after_the_store_load():
    store = _line_of(STORE_LOAD)
    reassert = _line_of(REASSERT)
    assert reassert > store, (
        f"the operator re-assert (line {reassert}) runs BEFORE the persisted "
        f"store load (line {store}). Both are include_vars, so the later wins — "
        "in this order the store wins and the operator's file is decoration."
    )


def test_the_reassert_reads_the_operator_file_and_not_the_defaults():
    """`default.credentials.yml` is a vars_file and already outranked; pointing
    the re-assert at it would restore nothing while looking like it did."""
    text = MAIN.read_text(encoding="utf-8")
    start = text.index(REASSERT)
    body = text[start: start + 400]
    assert re.search(r"playbook_dir\s*\}\}/credentials\.yml", body), (
        "the re-assert no longer globs `{{ playbook_dir }}/credentials.yml`. "
        "It must read the OPERATOR's gitignored file — re-reading the committed "
        "defaults would re-apply the empty templates it exists to override."
    )
    assert "default.credentials.yml" not in body, (
        "the re-assert points at default.credentials.yml, whose `minimax_api_key: \"\"` "
        "is the very empty value that shadowed the operator's key."
    )
