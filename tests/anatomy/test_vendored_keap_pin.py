"""Anatomy gate: vendored KEAP code has one home and the face mirrors it byte for byte.

files/anatomy/contracts/keap/ is the one home of KEAP's DataTable schema in nOS
(ssot/doctrine/cross-repo-contracts.md §1: no second copy that can diverge).
The face keeps a MIRROR because it must build from its own tree: it resolves
`zod` from its own node_modules and is synced alone to ~/face/src. A mirror
nothing compares is a fork with a delay on it, so this gate compares the bytes.
Re-vendor both with tools/vendor-keap-contracts.py, never by hand.
"""

from __future__ import annotations

import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
HOME = REPO / "files/anatomy/contracts/keap"
MIRROR = REPO / "files/anatomy/face/src/lib/keap-contracts"
FILES = ("visibility.ts", "table.ts", "field-concepts.ts")


def test_the_home_holds_every_vendored_file() -> None:
    assert sorted(p.name for p in HOME.glob("*.ts")) == sorted(FILES)


def test_the_face_mirror_is_byte_equal_to_the_home() -> None:
    drifted = [n for n in FILES if (MIRROR / n).read_bytes() != (HOME / n).read_bytes()]
    assert not drifted, (
        f"face mirror differs from files/anatomy/contracts/keap/: {drifted}. "
        "Edit neither by hand; run tools/vendor-keap-contracts.py."
    )
