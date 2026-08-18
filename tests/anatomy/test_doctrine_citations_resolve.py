"""Anatomy gate — every doctrine citation resolves, or is a NAMED finding.

Subject: tools/doctrine-cite.py (2026-08-06, the constitution layer).

THE CLAIM UNDER GATE: a citation ("§2.4", "DECISION 2b", "Constraint A",
"M7", "REM-118") asserts that a paragraph exists and says what the citing
code assumes. Measured before this gate existed: 694 §-citations across 130
files and NOT ONE was verified — the citation network was the largest body
of unchecked references in the estate, in the estate that refuses a dangling
`upstream:` at compile time.

WHAT IS FROZEN, and in which direction it may move:
  * KNOWN_FINDINGS — the exact residue on 2026-08-06, each verified by hand
    (see the tuple's comments). A NEW wrong/missing/unknown citation goes
    red; a REPAIRED one goes red too until it is removed from this set —
    the unmatched-authentik-slug shape, both directions.
  * UNQUALIFIED_CEILING — bare citations with no declared authority. 129 on
    2026-08-06. May shrink freely; may not grow: a new bare § is a new
    address that is not an address, and qualifying it costs one comment.
  * RESOLVED_FLOOR — the corpus must keep answering at least what it
    answers today; a heading sweep that silently orphans fifty citations
    is exactly what this catches.

Offline, ~2 s: the resolver walks committed files only.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _tool():
    spec = importlib.util.spec_from_file_location(
        "doctrine_cite", REPO / "tools" / "doctrine-cite.py")
    mod = importlib.util.module_from_spec(spec)
    # 3.13 dataclasses resolve their module through sys.modules at class
    # creation; an exec'd-but-unregistered module is a NoneType there.
    sys.modules["doctrine_cite"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def tool():
    return _tool()


@pytest.fixture(scope="module")
def resolved(tool):
    citations, corpus = tool.run()
    return citations, corpus


# ── unit refusals (fixture-level, independent of the live tree) ────────────


def test_a_dangling_section_is_classified_wrong(tool):
    corpus = {"docs/x.md": tool.DocIndex(path="docs/x.md", sections={"1": "One"})}
    c = tool.Citation("a.py", 1, "section", "9.9", "docs/x.md", "sameline")
    tool.resolve([c], corpus)
    assert c.status == "wrong"


def test_an_unqualified_citation_is_never_guessed(tool):
    """72 bare `§5`s were the measured problem; a resolver that guessed a doc
    for them would manufacture 72 confident lies. Unqualified stays its own
    class."""
    corpus = {"docs/x.md": tool.DocIndex(path="docs/x.md", sections={"5": "Five"})}
    c = tool.Citation("a.py", 1, "section", "5", None, "none")
    tool.resolve([c], corpus)
    assert c.status == "unqualified"
    assert c.doc is None


def test_an_external_standard_is_not_a_corpus_miss(tool, resolved):
    """'RFC 6749 §4.4.3' resolves against the IETF, not this repo — first run
    classified both blueprint comments as corpus-wrong."""
    citations, _ = resolved
    ext = [c for c in citations if c.shape == "external"]
    assert len(ext) >= 2
    assert all(c.status == "resolved-external" for c in ext)


# ── the live tree ──────────────────────────────────────────────────────────

#: The verified residue. EMPTY since 2026-08-18 — all four findings closed,
#: and each was closed by naming the truth rather than by widening a rule:
#:   §205             was a LINE-NUMBER wearing a section's syntax ("the plan
#:                    §205-209") on the same line as a doc it does not live
#:                    in. Now cites `docs/sso-autologin-plan.md` item 3 by name.
#:   two KEAP specs   cross-repo by design. The resolver now has a declared
#:                    FOREIGN_REPOS table and classes them `resolved-external`,
#:                    alongside RFCs — a citation into property we do not own
#:                    is a different KIND of claim, not a broken link
#:                    (docs/doctrine/foreign-properties.md).
#:   REM-088 ×3       a phantom id, never persisted (queue runs 087 -> 093).
#:                    Declared in PHANTOM_REM_IDS with its evidence and given
#:                    its own `phantom` class, because documenting a phantom
#:                    requires writing its id — the first attempt just moved
#:                    the same three findings four lines up the file.
#:
#: An empty set is a strong claim and it may not be defended by loosening the
#: classifier: `phantom` and `resolved-external` are SEPARATE classes and stay
#: visible in the tally for exactly that reason. A new residue goes here with
#: the verification note the old four carried.
KNOWN_FINDINGS: set[tuple[str, str, str, str]] = set()

#: Measured 2026-08-06 after the self-referential exclusion: 1061 citations,
#: 929 resolved, 124 unqualified. The floor sits just under the measurement
#: (parent-session commits land in this worktree continuously); the ceiling
#: is exact — bare citations only ever have permission to shrink.
UNQUALIFIED_CEILING = 124
RESOLVED_FLOOR = 925


def _live_findings(citations):
    return {(c.file, c.shape, c.key, c.status) for c in citations
            if c.status in ("wrong", "missing-doc", "unknown-id", "moved")}


def test_the_residue_is_exactly_the_known_findings(resolved):
    citations, _ = resolved
    live = _live_findings(citations)
    new = live - KNOWN_FINDINGS
    assert not new, (
        "NEW unresolvable citations — each is a claim about a paragraph that "
        "does not hold; fix the address or, if it is genuinely a new residue "
        "class, add it HERE with the verification note the others carry:\n  "
        + "\n  ".join(map(str, sorted(new)))
    )
    repaired = KNOWN_FINDINGS - live
    assert not repaired, (
        "citations in the frozen residue now resolve — good; remove them from "
        "KNOWN_FINDINGS so the freeze keeps matching reality:\n  "
        + "\n  ".join(map(str, sorted(repaired)))
    )


def test_moved_docs_do_not_accumulate(resolved):
    """`moved` auto-resolves against the archive/new home, which makes it easy
    to never repair. Zero today (all seven 2026-08-06 finds were repaired at
    the citing site); a moved citation may exist only as a KNOWN_FINDING."""
    citations, _ = resolved
    moved = [c for c in citations if c.status == "moved"
             and (c.file, c.shape, c.key, c.status) not in KNOWN_FINDINGS]
    assert not moved, (
        "citations resolving only via a moved doc — repair the citing "
        "address (a pointer fix, not new law):\n  "
        + "\n  ".join(f"{c.file}:{c.line} §{c.key} -> {c.doc}" for c in moved)
    )


def test_bare_citations_do_not_grow(resolved):
    citations, _ = resolved
    unqualified = [c for c in citations if c.status == "unqualified"]
    assert len(unqualified) <= UNQUALIFIED_CEILING, (
        f"{len(unqualified)} unqualified citations against a ceiling of "
        f"{UNQUALIFIED_CEILING} — a new bare § was added. One comment names "
        f"its document; write it, or the address space regresses"
    )


def test_the_corpus_keeps_answering(resolved):
    citations, corpus = resolved
    resolved_n = sum(1 for c in citations if c.status == "resolved")
    assert resolved_n >= RESOLVED_FLOOR, (
        f"only {resolved_n} citations resolve (floor {RESOLVED_FLOOR}) — "
        f"either a doctrine doc lost headings or the harvest broke"
    )
    assert len(citations) >= 1000, "harvest collapsed — the walk is broken, not clean"
    assert sum(len(i.sections) for i in corpus.values()) >= 1800


def test_the_header_heuristic_is_measured_not_assumed(resolved):
    """The coordinator's question, answered with a denominator: how often does
    a bare § resolve via the citing file's declared authorities? On
    2026-08-06: header+file-doc resolutions are the majority of all section
    resolutions, and the gate keeps the measurement from silently rotting."""
    citations, _ = resolved
    sections = [c for c in citations if c.shape == "section"]
    via_declared = [c for c in sections
                    if c.how in ("header", "file-doc") and c.status == "resolved"]
    assert len(via_declared) >= 300, (
        f"only {len(via_declared)} sections resolve via declared authorities — "
        f"the file-header convention broke down; re-measure before trusting it"
    )
