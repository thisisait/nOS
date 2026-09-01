"""Anatomy CI gate — a skipped comparison is never reported as agreement.

`tools/discovery-scan.py` was write-once: `file_rows` skips a slug that already
exists, so the tool could OPEN a finding and never close one. Measured
2026-09-01 — five of its own `obs-` rows described a world that had since been
reconciled:

    obs-queue-rem-159/-204/-226   the queue had been corrected days earlier
    obs-claude-md-backlog-tally   CLAUDE.md had stopped quoting the numbers
    obs-disabled-services-...     the probe had been taught to resolve
                                  config.yml, and every flag reads true there

The contradiction finder was holding records that had stopped being true. That
is the defect it exists to find, in its own output.

It still does not close them — closing stays a deliberate act with the reading
written into the row. What it now does is REPORT which rows no longer reproduce,
and the whole safety of that report rests on one distinction:

    a finding is absent because it was FIXED    -> report it
    a finding is absent because it was SKIPPED  -> say nothing

A probe skips when a `fix_version` is prose, a container cannot be read, or a
prerelease suffix will not compare. Treating those as agreement would have this
tool recommend retiring LIVE contradictions. `ScanResult.judge()` records only
comparisons that ran to a verdict, and `stale_rows` reports only those.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
TOOL = REPO / "tools" / "discovery-scan.py"


@pytest.fixture(scope="module")
def ds():
    spec = importlib.util.spec_from_file_location("discovery_scan", TOOL)
    mod = importlib.util.module_from_spec(spec)
    # dataclasses resolve annotations through sys.modules; without this the
    # @dataclass decorator raises on import.
    sys.modules["discovery_scan"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_a_judged_finding_that_vanished_is_reported(ds):
    res = ds.ScanResult()
    res.judge("obs-queue-rem-226")
    assert ds.stale_rows(res, {"obs-queue-rem-226": "queued"}) == {
        "obs-queue-rem-226": "queued"}


def test_a_skipped_pair_is_never_reported_stale(ds):
    """The one that matters. A skip must not read as agreement — REM-188 sits in
    exactly this state today (`fix_version: "11.8.8 (re-pull)"` is prose, the
    running tag is 11.8.8) and must NOT be recommended for closing."""
    res = ds.ScanResult()
    res.skip("queue or image version not strictly numeric")
    assert ds.stale_rows(res, {"obs-queue-rem-188": "queued"}) == {}, (
        "a pair the scan SKIPPED was reported as no longer reproducing. The "
        "contradiction may be entirely live; nothing compared it")


def test_a_finding_still_reproducing_is_not_reported(ds):
    res = ds.ScanResult()
    res.judge("obs-queue-rem-212")
    res.findings.append(ds.Finding(slug="obs-queue-rem-212", title="t", body="b"))
    assert ds.stale_rows(res, {"obs-queue-rem-212": "queued"}) == {}


def test_every_probe_records_a_verdict_and_not_a_bare_count(ds):
    """`res.compared += 1` without a matching slug is a comparison the stale
    report cannot see, so its row can never be retired however long it has been
    true. One exception is deliberate and named here: the disabled-services
    probe counts per-toggle inside its loop and judges the CLASS after it,
    because it files one row for N instances."""
    src = TOOL.read_text(encoding="utf-8")
    bare = [ln.strip() for ln in src.splitlines()
            if "res.compared += 1" in ln and not ln.lstrip().startswith("#")]
    assert bare == [
        "res.compared += 1   # per-var; the CLASS verdict is judged after the loop"
    ], (
        "a probe increments the compared counter without recording which slug "
        "it decided. That row can never be reported stale:\n  "
        + "\n  ".join(bare))


def test_an_unreadable_table_is_not_an_empty_one(ds):
    """`open_obs_rows` must raise rather than return {} on a failure — main()
    catches it and prints UNKNOWN. A silent {} would mean "nothing is stale",
    which is the shape of every other defect in this file's docstring."""
    import inspect
    src = inspect.getsource(ds.open_obs_rows)
    assert "except" not in src, (
        "open_obs_rows swallows its own error. An unreachable table would then "
        "report zero stale rows, which reads as a clean result")
