"""`nos dtt seed` never writes the committed roadmap index into the estate checkout.

WHY (2026-10-24, the first day of ~/.nos/estate): `nos dtt` runs the tools from
NOS_SRC, which is now the estate clone, and roadmap-seed regenerated the
committed state/roadmap/index.yml inside it. The estate went dirty and
`nos update` refused to move it ("has local changes"). The index is source: it
is regenerated in the development tree and reaches the estate by a commit and
`nos update`, never by a write in the estate.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import roadmap_seed_lib as lib  # noqa: E402


def _repo(tmp: Path, branch: str) -> Path:
    r = tmp / branch
    subprocess.run(["git", "init", "-q", "-b", branch, str(r)], check=True)
    return r


def test_an_estate_checkout_is_recognised(tmp_path):
    assert lib.is_estate_checkout(str(_repo(tmp_path, "estate"))) is True
    assert lib.is_estate_checkout(str(_repo(tmp_path, "dev"))) is False
    assert lib.is_estate_checkout(str(tmp_path / "not-a-repo")) is False


def test_the_seeder_skips_the_index_in_an_estate():
    src = (REPO / "tools" / "roadmap-seed.py").read_text(encoding="utf-8")
    assert "is_estate_checkout(_REPO)" in src, "roadmap-seed must ask before writing the index"
