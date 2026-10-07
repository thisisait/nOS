"""Anatomy gate: vendored KEAP code has one home, the face mirrors it, and it sits at the pin.

files/anatomy/contracts/keap/ is the one home of KEAP's DataTable schema in nOS
(ssot/doctrine/cross-repo-contracts.md §1: no second copy that can diverge).
The face keeps a MIRROR because it must build from its own tree: it resolves
`zod` from its own node_modules and is synced alone to ~/face/src. A mirror
nothing compares is a fork with a delay on it, so this gate compares the bytes.
Re-vendor both with tools/vendor-keap-contracts.py, never by hand.

THE PIN. Measured 2026-10-07: keap_repo_ref was v2.0.1 while the face copy said
v1.45.0 and the cortex copy v1.39.0, and nothing compared a header to the pin.
A schema older than the running KEAP validates defs the estate would refuse.
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
HOME = REPO / "files/anatomy/contracts/keap"
MIRROR = REPO / "files/anatomy/face/src/lib/keap-contracts"
FILES = ("visibility.ts", "table.ts", "field-concepts.ts")
DEFAULTS = REPO / "roles/pazny.keap/defaults/main.yml"
CORTEX_COPY = REPO / "files/anatomy/cortex/shared/contracts/field-concepts.ts"
TAG = re.compile(r"vendored from thisisait/nos-keap (?:at|@) (v\d+\.\d+\.\d+\S*)", re.I)

#: repo path -> (the tag it may lag at, why, what closes it). Empty is the goal.
_FORK = (
    "v1.45.0",
    "one snapshot; nOS hand-added rowRef to table.ts FACETABLE (ac5768d2), KEAP v2.0.1 "
    "lacks it, so a re-vendor makes schema-pin refuse account/invoice facets (2026-10-07)",
    "land the rowRef facet in KEAP, bump keap_repo_ref, re-vendor",
)
LAG: dict[str, tuple[str, str, str]] = {
    **{f"files/anatomy/contracts/keap/{n}": _FORK for n in FILES},
    **{f"files/anatomy/face/src/lib/keap-contracts/{n}": _FORK for n in FILES},
    "files/anatomy/cortex/shared/contracts/field-concepts.ts": (
        "v1.39.0", "the cortex organ's own copy", "I-7 (cortex re-vendor)"),
}


def test_the_home_holds_every_vendored_file() -> None:
    assert sorted(p.name for p in HOME.glob("*.ts")) == sorted(FILES)


def test_the_face_mirror_is_byte_equal_to_the_home() -> None:
    drifted = [n for n in FILES if (MIRROR / n).read_bytes() != (HOME / n).read_bytes()]
    assert not drifted, (
        f"face mirror differs from files/anatomy/contracts/keap/: {drifted}. "
        "Edit neither by hand; run tools/vendor-keap-contracts.py."
    )


def _pin() -> str:
    m = re.search(r'^keap_repo_ref:\s*"?([^"\s]+)"?', DEFAULTS.read_text(encoding="utf-8"), re.M)
    assert m, "keap_repo_ref not found in roles/pazny.keap/defaults/main.yml"
    return m.group(1)


def _vendored() -> dict[str, str | None]:
    """Every file whose header says it is a nos-keap copy, plus the known homes."""
    known = {*(HOME / n for n in FILES), *(MIRROR / n for n in FILES), CORTEX_COPY}
    scanned = {
        p for p in (REPO / "files").rglob("*")
        if p.suffix in (".ts", ".js", ".mjs", ".md") and "node_modules" not in p.parts and p.is_file()
    }
    out: dict[str, str | None] = {}
    for p in known | scanned:
        head = "\n".join(p.read_text(encoding="utf-8", errors="replace").splitlines()[:3])
        m = TAG.search(head)
        if m or p in known:
            out[str(p.relative_to(REPO))] = m.group(1) if m else None
    return out


def test_every_vendored_keap_file_names_its_tag() -> None:
    vendored = _vendored()
    assert len(vendored) >= 7, f"only {len(vendored)} vendored file(s) seen; the scan is blind"
    untagged = sorted(p for p, tag in vendored.items() if tag is None)
    assert not untagged, f"vendored KEAP file(s) with no source tag in their header: {untagged}"


def test_a_vendored_tag_is_the_pin_or_a_named_lag() -> None:
    pin = _pin()
    off = {p: t for p, t in _vendored().items() if t and t != pin and LAG.get(p, ("",))[0] != t}
    assert not off, (
        f"vendored KEAP file(s) not at keap_repo_ref {pin} and not on LAG:\n  "
        + "\n  ".join(f"{p}: {t}" for p, t in sorted(off.items()))
        + "\nRe-vendor (tools/vendor-keap-contracts.py) or add a LAG row naming why."
    )


def test_a_lag_row_is_still_lagging() -> None:
    pin, vendored = _pin(), _vendored()
    stale = sorted(p for p, (tag, *_r) in LAG.items() if vendored.get(p) != tag or tag == pin)
    assert not stale, f"LAG row(s) no longer describe the tree; delete them: {stale}"
