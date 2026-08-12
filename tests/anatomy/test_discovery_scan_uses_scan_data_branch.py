"""Gate — discovery-scan Probe C diffs the scan artefacts against scan-data.

The nightly scanner writes remediation-queue.json / scan-state.json and commits
them to the dedicated `scan-data` branch; `dev`/HEAD deliberately lags (the
reviewed subset). Probe C used to diff disk against HEAD, which manufactured a
contradiction out of that intended lag (measured 2026-08-12: disk 190 rows ==
scan-data 190, HEAD 188 → two false findings).

Disk legitimately matches EITHER ref depending on review lag (scan-data after a
fresh scan; HEAD after resolutions are reviewed on but scan-data hasn't caught
up). So Probe C fires only when disk matches NEITHER — the genuine "recorded
nowhere in git" case. This pins the fix AND its danger direction (a quieter probe
hides things) by proving:
  * disk == scan-data (HEAD trails) → NO finding — the original false positive,
  * disk == HEAD (scan-data trails) → NO finding — the post-resolution lag,
  * disk == neither                → a finding STILL fires.

Pure unit test: at_ref is monkeypatched, so no live git/branch/Docker is touched.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
MODPATH = REPO / "tools" / "discovery-scan.py"


def _load():
    spec = importlib.util.spec_from_file_location("discovery_scan", MODPATH)
    mod = importlib.util.module_from_spec(spec)
    # Register BEFORE exec so @dataclass can resolve cls.__module__.
    sys.modules["discovery_scan"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def mod():
    return _load()


def test_scan_data_is_a_baseline_ref(mod):
    assert mod.SCAN_DATA_REF in mod.SCAN_ARTEFACT_REFS, (
        "scan-data must be one of the baseline refs Probe C consults"
    )
    assert "HEAD" in mod.SCAN_ARTEFACT_REFS, "HEAD must remain a baseline ref too"


def test_baselines_collect_every_answering_ref(mod, monkeypatch):
    monkeypatch.setattr(
        mod, "at_ref",
        lambda ref, rel: {"scan-data": "SD", "HEAD": "HD"}.get(ref),
    )
    got = mod.scan_artefact_baselines("docs/llm/security/scan-state.json")
    assert dict(got) == {"scan-data": "SD", "HEAD": "HD"}


def _run_probe(mod, monkeypatch, disk_text, sd_text, head_text):
    """Run Probe C with disk / scan-data / HEAD forced to given contents."""
    monkeypatch.setattr(
        mod, "at_ref",
        lambda ref, rel: sd_text if ref == mod.SCAN_DATA_REF else head_text,
    )
    monkeypatch.setattr(mod, "HOST_WRITTEN", ["docs/llm/security/scan-state.json"])

    class _P:
        def is_file(self):
            return True

        def read_text(self, encoding="utf-8"):
            return disk_text

    monkeypatch.setattr(mod, "REPO", type("R", (), {"__truediv__": lambda self, o: _P()})())
    res = mod.ScanResult()
    mod.probe_artefact_vs_repo(res)
    return res


def test_disk_equals_scan_data_is_silent(mod, monkeypatch):
    # HEAD trails (the original false positive): disk == scan-data, disk != HEAD.
    res = _run_probe(mod, monkeypatch, '{"a":1}', sd_text='{"a":1}', head_text='{"a":0}')
    assert not res.findings, "disk matching scan-data must NOT fire (HEAD-trails lag)"
    assert res.compared == 1


def test_disk_equals_head_is_silent(mod, monkeypatch):
    # scan-data trails (post-resolution lag): disk == HEAD, disk != scan-data.
    res = _run_probe(mod, monkeypatch, '{"a":1}', sd_text='{"a":0}', head_text='{"a":1}')
    assert not res.findings, "disk matching HEAD must NOT fire (scan-data-trails lag)"


def test_disk_matches_neither_fires(mod, monkeypatch):
    res = _run_probe(mod, monkeypatch, '{"a":2}', sd_text='{"a":1}', head_text='{"a":0}')
    assert res.findings, "disk recorded in NO ref must still fire"
    assert "matches no committed ref" in res.findings[0].title
