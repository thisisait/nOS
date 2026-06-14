"""Anatomy gate — docs/rag-architecture.md exists and covers the MVP design.

WHY: The RAG substrate (Qdrant container, Bone embeddings API, Wing read-only
client, librarian agent profile) is partially LIVE and contract-defined, but
the MVP architecture document was missing — CLAUDE.md is the operator runbook,
not a RAG design doc, so a future operator/agent had no single authoritative
explanation of the design, the implemented-vs-deferred seams, the limitations,
the operator workflow, or the GDPR posture.

This gate pins the doc into existence AND pins its scope: every required
section the proposed fix enumerated must stay present (Overview, Corpus
sources, Architecture, Operator workflow, GDPR compliance, Limitations), the
load-bearing artifact names that anchor it to real code must remain referenced
(so the doc can't silently drift into vapor-spec), and the honest
implemented-vs-deferred framing (substrate live / ingest pipeline deferred,
librarian contract-only) must survive. Trips if the doc is deleted or any
required surface is dropped.
"""
from __future__ import annotations

import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
DOC = REPO / "docs" / "rag-architecture.md"


def _text() -> str:
    assert DOC.is_file(), (
        "docs/rag-architecture.md must exist — it is the authoritative MVP "
        "design for the nOS RAG / embeddings substrate"
    )
    return DOC.read_text()


def test_doc_exists_and_nonempty():
    """The doc exists and carries real content (≥ ~900 words)."""
    text = _text()
    words = len(text.split())
    assert words >= 900, (
        f"docs/rag-architecture.md has only {words} words — the design must "
        "cover the MVP in depth, not stub it"
    )


def test_required_sections_present():
    """The six sections the fix enumerated must all be present as headings."""
    text = _text()
    required = (
        "## 1. Overview",
        "## 2. Corpus sources",
        "## 3. Architecture",
        "## 4. Operator workflow",
        "## 5. GDPR compliance",
        "## 6. Limitations",
    )
    missing = [h for h in required if h not in text]
    assert not missing, (
        "docs/rag-architecture.md is missing required section heading(s): "
        + ", ".join(missing)
    )


def test_anchors_to_real_artifacts():
    """The doc must reference the real code artifacts so it can't drift to vapor."""
    text = _text()
    anchors = (
        "apps/qdrant.yml",                                   # the install half
        "files/anatomy/plugins/qdrant-base",                 # the wiring half
        "files/anatomy/agents/librarian",                    # the consumer agent
        "files/anatomy/bone/clients/qdrant_client.py",       # Bone client
        "/api/v1/embeddings/upsert",                         # Bone write route
        "/api/v1/embeddings/search",                         # Bone search route
    )
    missing = [a for a in anchors if a not in text]
    assert not missing, (
        "docs/rag-architecture.md dropped reference(s) to load-bearing "
        "artifacts: " + ", ".join(missing)
    )


def test_documents_three_reserved_collections():
    """All three reserved Qdrant collections must be named (corpus sources §)."""
    text = _text()
    collections = ("agent_outputs", "system_metadata", "cybersec_intel")
    missing = [c for c in collections if c not in text]
    assert not missing, (
        "docs/rag-architecture.md must name all three reserved collections; "
        "missing: " + ", ".join(missing)
    )


def test_honest_implemented_vs_deferred_framing():
    """The doc must keep the honest MVP framing — substrate live, ingest deferred."""
    text = _text().lower()
    # Librarian is contract-only / awaiting corpus until the ingest pipeline lands.
    assert "awaiting corpus" in text or "contract-only" in text, (
        "docs/rag-architecture.md must state the librarian is contract-only / "
        "returns 'awaiting corpus' on an empty store"
    )
    assert "deferred" in text, (
        "docs/rag-architecture.md must flag the corpus-population pipeline as "
        "DEFERRED — the honest implemented-vs-deferred map is the point of the MVP doc"
    )


def test_gdpr_posture_documented():
    """GDPR §: legal basis, 365-day retention, and Art. 17 erasure must appear."""
    text = _text()
    lower = text.lower()
    assert "legitimate_interests" in lower or "legitimate interests" in lower, (
        "GDPR section must state the legal basis (legitimate_interests)"
    )
    assert "365" in text, (
        "GDPR section must document the 365-day retention horizon"
    )
    assert "Article 17" in text or "Art. 17" in text, (
        "GDPR section must cover Article 17 erasure"
    )
