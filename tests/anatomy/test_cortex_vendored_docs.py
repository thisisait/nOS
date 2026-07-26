"""Anatomy gate — every vendored cortex spec declares where it came from.

`files/anatomy/cortex/docs/specs/` holds copies of KEAP specs. Nothing in CI can
diff them against their originals — KEAP is a different repo and is not checked
out here — so the copies drift silently. That is `docs/hidden_fees/11`, and it
ends only when the original is deleted rather than copied (S5).

Until then the cheapest real defence is provenance: a reader who opens a copy
must be able to see that it IS a copy, and of what. Without the header the
failure mode is someone editing the copy, believing they fixed the spec, and
losing the change at the next re-vendor.

The ledger (`docs/plans/cortex-specs-ledger.md`) claimed all eight carried a
header on 2026-07-25. Three did. This test is why that cannot happen again.
"""

from __future__ import annotations

import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
VENDORED = REPO / "files" / "anatomy" / "cortex" / "docs" / "specs"

FILES = sorted(VENDORED.glob("*.md"))


def test_vendored_dir_is_not_empty():
    """Guard the guard: a glob that matches nothing passes every parametrised case."""
    assert FILES, f"no vendored specs found under {VENDORED.relative_to(REPO)}"


@pytest.mark.parametrize("path", FILES, ids=[p.name for p in FILES])
def test_carries_provenance(path: pathlib.Path):
    head = "\n".join(path.read_text().splitlines()[:6])
    assert "Vendored from thisisait/nos-keap @" in head, (
        f"{path.name} has no provenance header in its first 6 lines. A vendored copy that "
        f"does not say it is a copy invites someone to edit it instead of the original — "
        f"the change then dies at the next re-vendor. Add:\n"
        f"  > Vendored from thisisait/nos-keap @ <tag> docs/specs/{path.name} — organ-side copy."
    )
