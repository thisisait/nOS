"""Pin: dtt-share-phase2-refusal spec exists and cites the visibility phase note.

The phase-2 swap is schema-invariant (visibility.ts). This gate fails if the
vendored phase note disappears, or if the seed spec (when present) no longer
cites it and the settled defaults a builder needs (agent:estate, KEAP_AGENT_BEARERS).
Success is a READ of those files, not a writer stamping itself.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
VISIBILITY = REPO / "files" / "anatomy" / "face" / "src" / "lib" / "keap-contracts" / "visibility.ts"

PHASE_NOTE = (
    "phase 2 swaps in per-agent bearers",
    "nOS CredentialResolver",
    "no change to any shape in this file",
    "agent:<x-keap-agent>",
)

SPEC_NEEDLES = (
    "visibility.ts",
    "CredentialResolver",
    "McpTablesTool",
    "schema-invariant",
    "agent:estate",
    "KEAP_AGENT_BEARERS",
    "x-keap-agent",
)


def test_visibility_phase_note_declares_schema_invariant_swap():
    src = VISIBILITY.read_text(encoding="utf-8")
    missing = [n for n in PHASE_NOTE if n not in src]
    assert not missing, (
        f"visibility.ts lost the phase-2 note {missing!r} — schema-invariant "
        "contract drifted; do not invent a shape change"
    )


def test_seed_spec_exists_and_cites_the_phase_note():
    seed_dir = Path(os.environ.get("NOS_SEED_DIR") or Path.home() / "projects" / "nos-seed")
    spec = seed_dir / "dtt-share-phase2-refusal.md"
    if not spec.is_file():
        pytest.skip(f"private seed spec not at {spec}")
    text = spec.read_text(encoding="utf-8")
    missing = [n for n in SPEC_NEEDLES if n not in text]
    assert not missing, (
        f"{spec.name} is not a builder spec citing the phase note; missing {missing!r}"
    )
