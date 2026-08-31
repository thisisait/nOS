"""A vendored copy that names its upstream has declared itself.

MEASURED 2026-08-31. `tools/cortex-drift.py` reported 13 UNDECLARED drifts
between the vendored cortex organ and `~/keap/src`. Seven were docs/specs whose
ONLY divergence is the provenance banner the organ adds to every copy:

    > Vendored from thisisait/nos-keap @ v1.28.0 (94acbfe) docs/specs/… —
      organ-side copy, P-4b Docs stage 2026-07-25. The KEAP original remains
      authoritative until the post-C4 docs cleanup.

That names the upstream, the version, the commit, the date and which side stays
authoritative. It is a declaration; it is simply not spelled `nOS Sn DIFF`,
which is a CODE convention — a marker block placed beside the lines it
justifies. A document whose entire divergence IS the banner has no lines for a
marker to sit beside.

WHY IT MATTERED. The tool's own docstring says reporting declared drift beside
an undeclared one-liner "would make the tool as unreadable as having no tool" —
and that is exactly what happened, in the other direction: seven benign files
stood in front of five real code drifts, one of them 79 lines in `fs-roots.ts`.
Recognising the banner took 13 to 6 and put the code drifts on top.

WHAT IT MUST NOT BECOME. A blanket amnesty. The banner counts only where it
actually appears, and a code file that diverges without either marker is still
undeclared — checked below, because a declaration test that passes everything
is worse than none.

Retro-verified 2026-08-31 by removing the banner pattern.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
TOOL = REPO / "tools/cortex-drift.py"
ORGAN = REPO / "files/anatomy/cortex"


def _mod():
    spec = importlib.util.spec_from_file_location("cortex_drift", TOOL)
    m = importlib.util.module_from_spec(spec)
    sys.modules["cortex_drift"] = m
    spec.loader.exec_module(m)
    return m


def test_the_banner_the_organ_actually_writes_is_recognised() -> None:
    m = _mod()
    real = (ORGAN / "docs/specs/recall-gate.md")
    if not real.is_file():
        import pytest
        pytest.skip("the vendored organ is not in this checkout")
    assert m.VENDOR_BANNER.search(real.read_text(encoding="utf-8")), (
        "the banner on a real vendored spec is not recognised as a "
        "declaration, so seven docs stand in front of the code drifts")


def test_a_code_marker_is_still_recognised() -> None:
    """The original convention must keep working; this added a spelling, it did
    not replace one."""
    m = _mod()
    assert m.DECLARED_DIFF.search("// ── nOS S2 DIFF 1/6 — the roots list ──")


def test_an_undeclared_file_is_still_undeclared() -> None:
    """The guard against amnesty. A file that diverges and says nothing must
    not become 'declared' because the tool learned a second spelling."""
    m = _mod()
    silent = "export const x = 1;\n// no marker, no banner\n"
    assert not m.DECLARED_DIFF.search(silent)
    assert not m.VENDOR_BANNER.search(silent)


def test_the_banner_must_name_an_upstream_and_a_version() -> None:
    """`> Vendored from` alone is a sentence, not a declaration — the value is
    that a reader can go and diff against a named point."""
    m = _mod()
    assert not m.VENDOR_BANNER.search("> Vendored from somewhere, at some point\n")
    assert m.VENDOR_BANNER.search("> Vendored from thisisait/nos-keap @ v1.28.0 docs/x.md\n")


def test_the_banner_is_only_a_declaration_at_the_top_of_a_quote() -> None:
    """Anchored to a blockquote line so prose that merely mentions the phrase —
    this file's own docstring, for instance — cannot declare anything."""
    m = _mod()
    assert not m.VENDOR_BANNER.search(
        "The organ was vendored from thisisait/nos-keap @ v1.28.0 last July.\n")
