"""Anatomy gate — no KEAP spec is copied into the cortex organ.

`files/anatomy/cortex/docs/specs/` held eight copies of KEAP specs. Nothing in
CI could diff them against their originals — KEAP is a different repo and is
not checked out here — so the copies drifted silently. That is
`docs/hidden_fees/11`, and it ends only when the original is cited rather than
copied (S5; ssot/doctrine/cross-repo-contracts.md §1: "A local copy MUST NOT
exist"). Measured 2026-10-07: the eight carried three different KEAP tags
(v1.27.0-v1.29.0) while the pin was v2.0.1.

The organ's code cites them tree-relative (`docs/specs/cortex-validate.md`);
tools/doctrine-cite.py resolves those as KEAP's (KEAP_PORT), never as ours.
"""

from __future__ import annotations

import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
ORGAN_DOCS = REPO / "files" / "anatomy" / "cortex" / "docs"


def test_no_keap_spec_is_copied_into_the_organ():
    copies = sorted(
        str(p.relative_to(REPO))
        for p in ORGAN_DOCS.rglob("*.md")
        if "Vendored from thisisait/nos-keap" in "\n".join(p.read_text().splitlines()[:6])
    )
    assert not copies, (
        f"KEAP spec copies inside nOS: {copies}. Cite the original as "
        "`KEAP docs/specs/<name>.md` and delete the copy — two copies diverge."
    )


def test_the_specs_dir_is_gone():
    assert not (ORGAN_DOCS / "specs").exists(), (
        "files/anatomy/cortex/docs/specs/ is back; KEAP's specs live in KEAP."
    )
