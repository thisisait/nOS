"""Anatomy CI gate — CLAUDE.md keeps the OnlyOffice/Documenso distinction.

The Docker-stacks table lists OnlyOffice under `b2b` and Documenso under `apps`
with no clue that they serve orthogonal purposes (collaborative *editing* vs
*e-signature*). That visual ambiguity could mislead an operator into thinking
the euro-office editing-engine pilot subsumes Documenso — it does not (e-signing
needs immutability; editing needs mutability). The clarification existed only in
a 2026-06-13 pilot devlog + the onlyoffice role defaults, never in the
authoritative guide.

This pins the clarifying footnote in CLAUDE.md so the distinction can't silently
fall out: it must name both services, mark them independent / non-competing, and
the file paths it cites for provenance must actually exist on disk.
"""

from __future__ import annotations

import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
CLAUDE_MD = REPO / "CLAUDE.md"

# Provenance paths the footnote cites — must stay real (no dead breadcrumbs).
CITED_PATHS = (
    "roles/pazny.onlyoffice/defaults/main.yml",
    "docs/devlog/nos-core/2026/2026-06-13-euro-office-pilot.md",
    "apps/documenso.yml",
)


def _footnote() -> str:
    text = CLAUDE_MD.read_text(encoding="utf-8")
    marker = "OnlyOffice (euro-office) vs Documenso"
    idx = text.find(marker)
    assert idx != -1, (
        "CLAUDE.md must carry the OnlyOffice/Documenso independence footnote "
        f"(marker '{marker}' not found)"
    )
    # Footnote is a single blockquote paragraph; grab to the next blank line.
    return text[idx : text.find("\n\n", idx)]


def test_footnote_names_both_services_as_independent():
    block = _footnote()
    for needed in ("OnlyOffice", "euro-office", "Documenso"):
        assert needed in block, f"footnote must name '{needed}'"
    # The doctrine: they do NOT compete / are independent.
    assert "independent" in block.lower() and "non-competing" in block.lower()


def test_footnote_states_the_orthogonal_purposes():
    block = _footnote().lower()
    # OnlyOffice = editing engine; Documenso = e-signature platform.
    assert "editing" in block, "footnote must call OnlyOffice an editing engine"
    assert "e-signature" in block or "e-sign" in block, (
        "footnote must call Documenso an e-signature platform"
    )
    # The rationale that makes them non-substitutable.
    assert "immutab" in block and "mutab" in block, (
        "footnote must state the mutability vs immutability rationale"
    )


def test_footnote_cites_only_real_paths():
    block = _footnote()
    for rel in CITED_PATHS:
        assert rel in block, f"footnote must cite {rel} for provenance"
        assert (REPO / rel).is_file(), f"footnote cites a missing path: {rel}"
