"""Anatomy gate: the w-datalog vendor decision states true conditions, and any
vendored copy honors them.

THREE DEFECTS IN THE DECISION, all measured on the chosen upstream
(semantica's datalog_reasoner.py) before any byte of it entered this tree:

  1. TERMINATION WAS SOLD AS THE SAFETY PROPERTY. The engine terminates on
     finite graphs, but `derive_all()` loops until the delta empties with no
     iteration, fact-count, or wall-clock cap. Measured at this estate's own
     scale: the textbook 2-rule ancestor closure over a 790-node chain (the
     taxonomy's size) derives 312,444 facts in ~142 s; `pair(X,Y) :- node(X),
     node(Y)` derives 624,890 facts in ~2 s. Termination is necessary, not
     sufficient — the same distinction the STRICT health wait already draws.

  2. THE PARSER IS FAIL-OPEN. Body parsing is a regex findall that keeps what
     matches and never checks residue: `not r(X)` is accepted with the `not`
     silently stripped (deriving the semantic INVERSE of the author's intent),
     and comparison guards (`A > 18`) vanish the same way. A ground query on a
     true fact answers no (the empty-binding row is dropped).

  3. "IMPORTS ONLY re/collections/dataclasses/typing" WAS FALSE. The file also
     imports two semantica-internal modules (logging wrapper + a 1,656-line
     progress tracker) at seven call sites, so it cannot be vendored
     byte-identical.

The fix is the vendor-contract pattern (commit 606046e6: compare DECLARATIONS,
not bytes): docs/idea/02-cortex-lang.md now declares the divergence set —
stripped imports, hard budgets (`max_derived_facts` / `max_iterations` /
`max_seconds`, failing closed), strict fail-closed parsing — and this gate
holds both ends: the doc must keep declaring the conditions, and a vendored
datalog_reasoner.py, whenever it lands, must contain them. Today the vendored
half passes vacuously; the day someone vendors the upstream file unedited, it
goes red before the file's first import.
"""

from __future__ import annotations

import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
DOC = REPO / "docs/idea/02-cortex-lang.md"
LOOP_DOC = REPO / "docs/idea/11-agentic-loop.md"

# The budget parameters the doc commits the vendored copy to. Declared here
# and in the doc; the vendored file must define all three.
BUDGET_TOKENS = ("max_derived_facts", "max_iterations", "max_seconds")


def _doc() -> str:
    return DOC.read_text(encoding="utf-8")


def test_the_stdlib_only_claim_is_corrected() -> None:
    text = _doc()
    assert "importing only `re`/`collections`/`dataclasses`/`typing`" not in text, (
        "02-cortex-lang.md is back to claiming the upstream file imports only "
        "four stdlib modules. It imports semantica-internal logging and "
        "progress-tracker modules at seven call sites; a decision that hides "
        "the required edit hides that the vendor is a fork."
    )
    assert "progress_tracker" in text, (
        "the doc no longer names the internal imports the vendored copy must "
        "strip — the divergence set is the vendor contract's comparison "
        "baseline, and an undeclared divergence is what 606046e6 exists to "
        "prevent."
    )


def test_termination_is_not_oversold() -> None:
    text = _doc()
    assert "necessary, not sufficient" in text, (
        "the doc dropped the amendment that termination is necessary, not "
        "sufficient. An unbudgeted fixpoint over model-authored rules is a "
        "resource bomb that happens to halt: 312,444 facts / ~142 s for the "
        "textbook closure at the estate's own 790-node scale."
    )
    for token in BUDGET_TOKENS:
        assert token in text, (
            f"the doc no longer declares the budget cap `{token}`. The vendor "
            "condition is hard caps on derived facts, iterations and wall "
            "time, failing closed — remove one and the vendored-copy half of "
            "this gate loses its baseline."
        )


def test_the_parser_condition_is_declared() -> None:
    text = _doc()
    assert "unconsumed input" in text, (
        "the doc no longer requires the vendored parser to raise on "
        "unconsumed input. Upstream silently strips `not` and comparison "
        "guards — accepting a rule while inverting its semantics is the "
        "opposite of the fail-closed doctrine the same document invokes."
    )


def test_the_loop_doc_credits_the_schema_not_the_implementation() -> None:
    """11-agentic-loop.md §6c: the same upstream, cited for what it measured.

    The section originally credited semantica with 'decisions [as] first-class
    graph nodes with causal ancestry' plus precedent search. Measured: the
    headline `find_similar_decisions()` similarity is bag-of-words Jaccard
    (its `use_semantic_search` parameter is never read), and the headline
    causality is entity co-occurrence plus timestamp order — guessed, not
    recorded. The schema and the PROV-O export are worth taking; the
    implementations are not, and the doc must say which is which.
    """
    text = LOOP_DOC.read_text(encoding="utf-8")
    assert "Jaccard" in text, (
        "§6c no longer says the upstream precedent search is bag-of-words "
        "Jaccard — the citation is back to admiring a docstring."
    )
    assert "co-occurrence" in text, (
        "§6c no longer says the upstream 'causal ancestry' is inferred from "
        "entity co-occurrence — a reader will import guessed lineage as if it "
        "were the recorded actor_action_id kind."
    )
    assert "ships the shape" not in text, (
        "§6c reverted to the unqualified endorsement. Credit the decision "
        "SCHEMA and the PROV-O export; the headline implementations are naive "
        "and this estate's lineage is already recorded, not guessed."
    )


def test_a_vendored_copy_honors_the_declared_conditions() -> None:
    """Vacuous until the file lands; red the day it lands unedited."""
    copies = [
        p
        for p in REPO.rglob("datalog_reasoner.py")
        if "node_modules" not in p.parts and ".git" not in p.parts
    ]
    for copy in copies:
        text = copy.read_text(encoding="utf-8")
        for token in BUDGET_TOKENS:
            assert token in text, (
                f"{copy.relative_to(REPO)} was vendored without the declared "
                f"budget cap `{token}` (docs/idea/02-cortex-lang.md). An "
                "unbudgeted derive_all() at 790-node scale is minutes of CPU "
                "from one well-formed rule."
            )
        assert "unconsumed" in text, (
            f"{copy.relative_to(REPO)} was vendored without the strict parser "
            "the decision requires — upstream's regex findall keeps matching "
            "atoms and silently drops `not` and comparison guards."
        )
