"""Anatomy CI gate — the smoke runner can read the gates its catalog declares.

MEASURED on run 33651218229 (2026-09-02): the cortex-executor row carries
`when: install_wing | default(true) and install_keap | default(false)` — the
right gate — but `evaluate_when` parsed only single atoms and fell through to
permissive on anything compound. The row ran everywhere KEAP is off (CI and a
fresh macOS default install alike) and failed with Wing's own 502.

A gate the evaluator cannot read is prose. This pins: compound ANDs evaluate;
and every `when:` in the committed catalog is either readable or consciously
permissive (OR stays permissive by design — over-report, never drop).
"""

from __future__ import annotations

import importlib.util
import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]


def _mod():
    spec = importlib.util.spec_from_file_location("_smoke", REPO / "tools" / "nos-smoke.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_compound_and_is_evaluated():
    ew = _mod().evaluate_when
    gate = "install_wing | default(true) and install_keap | default(false)"
    assert ew(gate, {}) is False, (
        "the cortex-executor gate reads permissive with KEAP off — the row "
        "then 502s on every host without KEAP, which is the measured defect")
    assert ew(gate, {"install_keap": True}) is True
    assert ew("a | default(true) and b | default(true)", {"b": False}) is False


def test_every_catalog_when_resolves_deliberately():
    """No committed row may depend on the permissive fallback by accident:
    a `when:` with ` and ` must flip when its atoms flip."""
    mod = _mod()
    catalog = yaml.safe_load((REPO / "state" / "smoke-catalog.yml").read_text(
        encoding="utf-8"))
    rows = catalog if isinstance(catalog, list) else next(
        v for v in catalog.values() if isinstance(v, list))
    checked = 0
    for row in rows:
        expr = (row or {}).get("when")
        if not expr or " and " not in str(expr):
            continue
        checked += 1
        on = mod.evaluate_when(str(expr), {n: True for n in _names(str(expr))})
        off = mod.evaluate_when(str(expr), {n: False for n in _names(str(expr))})
        assert on is True and off is False, (
            f"catalog when {expr!r} does not respond to its own atoms — the "
            "evaluator is treating it as prose and running it permissively")
    assert checked >= 1, (
        "no compound when found in the catalog — the population this gate "
        "guards is gone; re-read whether the cortex-executor row still exists")


def _names(expr: str) -> list[str]:
    import re
    return re.findall(r"\b([a-z_][a-z0-9_]*)\s*\|", expr)
