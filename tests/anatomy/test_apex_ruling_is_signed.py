"""The committed apex ruling matches its signed_digest.

2026-10-16 origin/dev carried a ruling whose signed_digest no longer matched (a
graph node added a withheld entry; the operator's --confirm was never committed),
and CI stayed green: no gate recomputed the digest. This one does, with
tools/apex-sign.py's own digest(), so the two can never disagree on the formula.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RULING = REPO / "files/anatomy/apex/ruling.yml"

_spec = importlib.util.spec_from_file_location("apex_sign", REPO / "tools/apex-sign.py")
apex_sign = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(apex_sign)


def unsigned(path: Path) -> str | None:
    """Why the ruling at `path` is not signed, or None when it is."""
    text = path.read_text(encoding="utf-8")
    have, want = apex_sign.recorded(text), apex_sign.digest(text)
    if have == want:
        return None
    return (f"{path.name}: signed_digest {str(have)[:16]}... != computed {want[:16]}...; "
            "the ruling changed since it was signed. Run tools/apex-sign.py (read the diff), "
            "then tools/apex-sign.py --confirm, then commit files/anatomy/apex/ruling.yml")


def test_the_committed_ruling_is_signed():
    assert unsigned(RULING) is None, unsigned(RULING)


def test_an_added_node_line_is_caught(tmp_path):
    # The 2026-10-16 shape: a node gained a withheld entry. Appending needs no
    # existing line, so rewording the ruling cannot break this self-test.
    copy = tmp_path / "ruling.yml"
    copy.write_text(RULING.read_text(encoding="utf-8") + '  "service:new-node": { publish: withheld }\n',
                    encoding="utf-8")
    msg = unsigned(copy)
    assert msg and "tools/apex-sign.py --confirm" in msg, msg
