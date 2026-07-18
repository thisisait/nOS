"""Anatomy CI gate — nOS-face wiring contract.

The face shell (vendored at files/anatomy/face/) is wired into nOS by a small set
of load-bearing contracts documented in docs/doctrine/face.md: forward_auth SSO +
edge-token trust, the Wing catalog, the Bone VFS/user-state, and the KEAP config
DataTables. This gate pins that wiring so a future change can't silently break it
(a client reading uid, a `{@html}` hole, a DataTable def with no seeder, a compose
env missing the edge token).

It runs the SAME checks as the `tools/face-wiring-report.py` linter (report↔gate
pairing, the repo idiom) so the two can never drift: each check must return no
violations.
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
_REPORT = REPO / "tools" / "face-wiring-report.py"


def _load_report():
    spec = importlib.util.spec_from_file_location("face_wiring_report", _REPORT)
    assert spec and spec.loader, "cannot load tools/face-wiring-report.py"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


REPORT = _load_report()


@pytest.mark.parametrize("label,fn", REPORT.CHECKS, ids=[c[0] for c in REPORT.CHECKS])
def test_face_wiring_check_passes(label, fn):
    fails = fn()
    assert fails == [], f"{label}: " + "; ".join(fails)
