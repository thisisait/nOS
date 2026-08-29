"""The corpus generator runs, and the free oracle is weaker than the row assumed.

`local-llm-corpus` reads: *"Synthesise chains from the opcode registry, run them
through cortex-validate, keep the valid ones... Distillation where the teacher
runs once and the correctness filter is code. This is an unusually good starting
position — most fine-tuning projects have no oracle to filter on."*

MEASURED 2026-08-29, by building the generator and running it:

    stage forms  142      chains tried 20 306 (depth 2)
    chains VALID 20 306   rejected 0        — 100.0%

A filter that accepts everything is not a filter. `analyzeCortex` rejects
STAGE-LOCAL faults — unknown opcode, unknown param, arity — and imposes no rule
on composition at all: `insert | classify` and `classify | insert` both pass,
`rank()` four times passes. So the oracle is free and real about SYNTAX, and
says nothing about whether a chain means anything. A corpus filtered on validity
alone is a grammar drill, and grammar is the one thing the validator can already
check at inference time without a model.

That does not sink the row; it moves its value. What discriminates between these
20 306 chains is the WARNING set (`deferred_namespace`, `mutating_default_dry_run`,
`commit_requires_confirm_gate`) and the natural-language pairing the row defers
to a large model. Both are real work. "The correctness filter is code" is not.

This file pins the measurement so the row cannot be picked up on the old premise,
and pins the generator so it keeps running. It deliberately does NOT assert the
exact corpus size — that moves with the registry, and a gate that fails when an
opcode is added would be a gate against doing the work.
"""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
CORTEX = REPO / "files/anatomy/cortex"
GEN = CORTEX / "scripts/corpus-gen.ts"

pytestmark = pytest.mark.skipif(
    not (CORTEX / "node_modules/.bin/tsx").exists(),
    reason="cortex node_modules absent — run `npm ci` in files/anatomy/cortex",
)


def _run(*args: str) -> dict:
    done = subprocess.run(
        ["npx", "tsx", str(GEN), "--json", *args],
        capture_output=True, text=True, timeout=600, cwd=CORTEX)
    assert done.returncode == 0, done.stderr[-600:]
    return json.loads(done.stdout)


def test_the_generator_runs_and_covers_every_opcode() -> None:
    """A generator that silently skips an opcode measures a smaller space than
    the one that exists — and would hide exactly the gap it is built to find."""
    got = _run("--max-stages", "1")
    assert got["registryOpcodes"] >= 15
    assert got["stagesEnumerated"] > got["registryOpcodes"], (
        "fewer stage forms than opcodes — the operand/param expansion is not "
        "running, so this measures the registry rather than the space")
    assert got["opcodesWithoutAValidChain"] == [], (
        f"no valid chain could be built for {got['opcodesWithoutAValidChain']}; "
        "either the OPERAND samples are wrong for that namespace, or the opcode "
        "cannot legally be called at all")


def test_validity_does_not_discriminate_between_composed_chains() -> None:
    """The finding, kept runnable.

    If this ever fails — if composed chains start being rejected — the row's
    original premise has become true and `local-llm-corpus` should be re-read
    as written rather than as corrected here.
    """
    got = _run("--max-stages", "2")
    assert got["chainsTried"] > 1000, "too few chains to say anything"
    assert got["chainsRejected"] == 0, (
        f"{got['chainsRejected']} composed chains were rejected — the analyzer "
        "has gained a compositional rule since 2026-08-29. The oracle may now "
        "filter sense as well as syntax; re-measure before trusting either "
        "reading of local-llm-corpus."
    )


def test_the_warnings_are_the_signal_that_is_left() -> None:
    """What a corpus built here can actually be sorted on."""
    got = _run("--max-stages", "2")
    assert got["warningsByCode"], (
        "no warnings at all across twenty thousand chains — then nothing in "
        "this corpus distinguishes one chain from another, and the generator "
        "produces training data with no gradient in it")
    assert "deferred_namespace" in got["warningsByCode"]


def test_the_corpus_is_reproducible() -> None:
    """A corpus is a fixture you diff, not a sample you trust. No RNG, no clock."""
    src = GEN.read_text(encoding="utf-8")
    for forbidden in ("Math.random", "Date.now", "new Date("):
        assert forbidden not in src, (
            f"{forbidden} in the generator — two runs would emit different "
            "corpora and neither could be reviewed against the other")
    assert _run("--max-stages", "1") == _run("--max-stages", "1")


def test_it_stays_out_of_the_vendored_tree() -> None:
    """`tools/cortex-drift.py` compares server/ shared/ knowledge/ docs/ against
    KEAP. A generator written into one of those would read as undeclared drift
    for ever; scripts/ is local by convention (ann-corpus.mjs is its sibling)."""
    drift = (REPO / "tools/cortex-drift.py").read_text(encoding="utf-8")
    assert 'VENDORED = ("server", "shared", "knowledge", "docs")' in drift, (
        "the vendored set changed — check that scripts/ is still outside it")
    assert GEN.parent.name == "scripts"
