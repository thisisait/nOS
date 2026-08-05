"""A probe that is never called reports nothing, and reports it as success.

WHY THIS EXISTS. discovery-scan.py's whole verdict is `0 contradiction(s)` or
`N contradiction(s)`, and a probe that main() forgets to call contributes
exactly as much to that verdict as a probe that found nothing: zero. The output
is indistinguishable. So the failure mode is not "the probe is broken" — a
broken probe usually throws — it is "the probe is absent from the run", which
looks precisely like a clean estate.

This estate has already paid for that shape twice, in code that was not
recursive and had no LLM anywhere near it: a nightly drift watcher that
produced no verdict for months while exiting 0, and a Linux wet-test that
passed `0/0 ready` against a stack with nothing in it. Both were silent, both
reported success, both were believed.

THE GATE IS DELIBERATELY WEAK. It does not check what a probe finds, or that it
finds anything — a scanner whose probes must fire to pass is a scanner that
rewards noise. It checks only the property that makes the verdict mean
anything: every probe defined is a probe run. Passing it implies far more than
pinning any single probe's output would, and there is nothing to overfit to.
(Bennett, AGI-23 — prefer the weakest gate that still fails.)

Retro-red: verified by deleting the `probe_doc_claim_vs_queue(res)` call from
main() with the function left in place. Red, naming that probe.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SCANNER = Path(__file__).resolve().parents[2] / "tools/discovery-scan.py"


def _tree() -> ast.Module:
    return ast.parse(SCANNER.read_text(encoding="utf-8"))


def _probe_names(tree: ast.Module) -> list[str]:
    return [n.name for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name.startswith("probe_")]


def _called_in_main(tree: ast.Module) -> set[str]:
    main = next((n for n in tree.body
                 if isinstance(n, ast.FunctionDef) and n.name == "main"), None)
    if main is None:
        return set()
    return {node.func.id for node in ast.walk(main)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}


def test_the_scanner_is_readable():
    """Positive control — an unparseable scanner makes everything below vacuous."""
    assert SCANNER.is_file(), "tools/discovery-scan.py is gone; this gate is blind"
    assert len(_probe_names(_tree())) >= 2, (
        "fewer than two probes found. Either the scanner was gutted or the "
        "`probe_` naming convention this gate keys on has been abandoned — in "
        "which case the gate is checking a convention nobody follows."
    )


@pytest.mark.parametrize("probe", _probe_names(_tree()))
def test_every_probe_is_actually_run(probe):
    assert probe in _called_in_main(_tree()), (
        f"{probe}() is defined but main() never calls it. It will contribute "
        f"nothing to the verdict, and the verdict will say '0 contradictions' "
        f"— indistinguishable from an estate that agrees with itself. Wire it "
        f"into main() or delete it; a dormant probe is worse than a missing "
        f"one, because it reads as coverage."
    )
