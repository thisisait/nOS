"""The loop's entry may not deprioritise a row on a rendered sentence.

MEASURED 2026-08-31. `tools/loop-propose.py` picks the worst never-proposed
weakness, and it was picking a `high` while a `critical` sat open:

    critical  rem:REM-212  open   portainer: vendor_blocked — Cycle-35 batch-57
    high      rem:REM-239  open   bookstack: version_bump — Cycle-46 batch-59

The filter was `"vendor_blocked" not in w["title"]`. REM-212 was FILED as
`remediation_type: vendor_blocked` when portainer had no fixed release. On
2026-08-27 upstream shipped 2.45.0; the scan moved the row's STATUS to
`pending` and confirmed the tag on Docker Hub, and left the type label alone —
it records how the row was filed, not what is true now. A substring match on
the rendered title read the stale label and pushed the queue's only actionable
CRITICAL behind a `high`.

THE PROPERTY WAS ALREADY GUARANTEED UPSTREAM, which is why the fix was a
deletion. `_source_remediation` emits only rows whose status is `pending`, and
`vendor-blocked` is a separate status carried by 5 rows today. Everything
reaching the ranking function has already been gated on the exact property the
filter re-derived — badly, from prose.

WHAT THIS GATE PINS. Not "no filter may exist" — a future one may be right.
It pins the OUTCOME: given a set of weaknesses, the ranking must return one of
the worst severity present. A filter that drops the top severity class has to
justify itself against this test rather than slip in as a one-line predicate.

Retro-verified 2026-08-31 by restoring the title-substring filter.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
PROPOSE = REPO / "tools/loop-propose.py"

_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


class _Status:
    """The reader `pick()` leans on, with the two calls it makes."""

    def __init__(self, rows):
        self._rows = rows

    def live_weaknesses(self):
        return self._rows, None

    def collect(self):
        return {"sources": []}          # nothing proposed against yet

    @staticmethod
    def _source_of(wid):
        return wid.split(":", 1)[0]


_MOD = None


def _module():
    """ONE module object, cached. Loading it twice gives two distinct `Refused`
    classes, and `pytest.raises` on the wrong one fails with the exception it
    was waiting for — which reads as the code being broken."""
    global _MOD
    if _MOD is None:
        spec = importlib.util.spec_from_file_location("loop_propose_pick", PROPOSE)
        _MOD = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = _MOD
        spec.loader.exec_module(_MOD)
    return _MOD


def _pick(rows, wanted=None):
    return _module().pick(_Status(rows), wanted)


def _w(wid, severity, title):
    return {"id": wid, "severity": severity, "title": title, "proposable": True}


def test_a_critical_is_not_outranked_by_its_own_label() -> None:
    """The exact live shape: a critical whose title carries the stale word, and
    a high that does not."""
    rows = [
        _w("rem:REM-212", "critical", "portainer: vendor_blocked — Cycle-35 batch-57"),
        _w("rem:REM-239", "high", "bookstack: version_bump — Cycle-46 batch-59"),
    ]
    got = _pick(rows)
    assert got["severity"] == "critical", (
        f"picked {got['id']} ({got['severity']}) while a critical was open. A "
        "word inside the title is deciding the ranking, and the queue's own "
        "status field already says whether a row is actionable.")


def test_the_worst_severity_present_is_always_what_is_returned() -> None:
    """Generalised, so the next filter has to answer to the outcome rather than
    to REM-212 by name."""
    for worst in ("critical", "high", "medium"):
        rows = [_w(f"rem:A-{worst}", worst, "anything at all")]
        rows += [_w(f"rem:B-{s}", s, "vendor_blocked upstream_patch wontfix")
                 for s in ("low", "info")]
        got = _pick(rows)
        assert got["severity"] == worst, (
            f"with {worst} present the ranking returned {got['severity']}")


def test_an_unproposable_row_is_still_excluded() -> None:
    """Deleting the vendor filter must not have deleted the evidence gate: a
    row whose evidence is uncommitted still cannot key a ceiling, and that
    exclusion is load-bearing."""
    rows = [
        {"id": "rem:REM-1", "severity": "critical", "title": "x", "proposable": False},
        _w("rem:REM-2", "low", "y"),
    ]
    got = _pick(rows)
    assert got["id"] == "rem:REM-2", (
        "a withheld critical was handed to the proposer; the engine would "
        "refuse it and the run would be spent")


def test_an_empty_queue_refuses_rather_than_returning_nothing() -> None:
    with pytest.raises(_module().Refused):
        _pick([])
