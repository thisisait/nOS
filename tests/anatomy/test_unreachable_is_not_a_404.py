"""Anatomy CI gate — nothing answering is not a service answering wrongly.

curl reports `000` whether the estate is down or Docker's host→container
forwarding is (hidden fee 43). From the host those are the same string, and on
2026-09-01/02 both the smoke and the hub audit read 13 healthy services as
broken — twice, ~40 minutes each.

`404`/`5xx` mean a service answered and answered wrongly: routing drift.
`000`/`ERR` mean nothing answered: a transport verdict about one hop.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
HUB = REPO / "tests" / "anatomy" / "test_hub_url_audit.py"
SMOKE = REPO / "tools" / "nos-smoke.py"


def _hub():
    spec = importlib.util.spec_from_file_location("hub_audit", HUB)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["hub_audit"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_the_hub_gate_separates_the_two():
    m = _hub()
    assert "000" not in m.HARD_FAIL and "ERR" not in m.HARD_FAIL, (
        "the hub audit counts an unreachable service as auto-wiring drift; it "
        "cannot tell a 404 from a forwarder that is not forwarding")
    assert {"000", "ERR"} <= m.UNREACHABLE
    assert {"404", "500", "502", "503"} <= m.HARD_FAIL, (
        "a real 404 must still be drift — this gate must not have made the "
        "audit unable to fail")


def test_the_hub_gate_still_fails_on_a_real_404():
    """The dangerous direction. Widening UNREACHABLE until nothing is drift
    would 'fix' the noise by removing the audit."""
    m = _hub()
    assert m.HARD_FAIL & {"404", "500", "502", "503"}, "HARD_FAIL is empty of real faults"
    assert not (m.HARD_FAIL & m.UNREACHABLE), "a code cannot be both"


@pytest.mark.parametrize("needle", [
    'r.status is None',            # the classifier
    'unreachable',                 # the summary word
    'TRANSPORT verdict',           # the sentence that stops the misreading
])
def test_the_smoke_reports_unreachable_separately(needle):
    src = SMOKE.read_text(encoding="utf-8")
    assert needle in src, (
        f"tools/nos-smoke.py no longer distinguishes unreachable from failed "
        f"({needle!r} is gone). A run where nothing answers reads as N broken "
        f"services, which is what fee 43 cost twice in one day")


def test_the_smoke_still_counts_a_wrong_answer_as_failed():
    """`bad` must remain the count of probes that ANSWERED and answered wrongly.
    If unreachable were folded into ok, a dead estate would smoke green."""
    src = SMOKE.read_text(encoding="utf-8")
    assert "bad = len(results) - ok - unreach" in src, (
        "the failed count no longer excludes only unreachable; a probe that "
        "answered wrongly must still be failed")
    assert 'if bad == 0 and unreach == 0:' in src, (
        "the green banner no longer requires zero unreachable — an estate "
        "nothing can reach would print a pass")
