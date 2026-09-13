"""A preflight that reports OK with no snapshot mechanism is a lie.

WHY THIS IS A GATE. `tmutil localsnapshot` is documented to need a Time
Machine destination. This host has none (measured). The temptation is to
read APFS-on-Data as 'we could snapshot' and print OK. That is the net
`docs/hidden_fees/08` already paid for: absence reading as ready.

Pinned:

1. `claimable()` is False when TM dest is absent AND no alternate path.
2. `preconverge-snapshot.plan(..., dry_run=True)` therefore has ok=False,
   and its text says REFUSED, not OK.
3. An injected alternate path MAY set ok=True without a TM destination —
   that is the escape hatch the tool names, not a silent pass.
4. Recovery text is `mount_apfs` + copy, never a bootloader undo.

The reader (`snapshot-status.py`) still must not CALL localsnapshot; that
stays on `test_the_new_readers_only_read.py`.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
STATUS = REPO / "tools/snapshot-status.py"
PRE = REPO / "tools/preconverge-snapshot.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def status():
    return _load(STATUS, "nos_snapshot_status")


@pytest.fixture(scope="module")
def pre():
    return _load(PRE, "nos_preconverge_snapshot")


def test_the_tools_this_gate_describes_exist():
    assert STATUS.is_file() and PRE.is_file()
    assert STATUS.stat().st_mode & 0o111
    assert PRE.stat().st_mode & 0o111


def test_claimable_is_false_without_tm_or_alternate(status):
    claim = status.claimable(
        {"ok": False, "why": "no destinations configured"},
        {"ok": False, "via": None, "why": "no alternate"},
    )
    assert claim["ok"] is False, (
        "claimable() returned {claim['ok']!r} with no TM dest and no "
        "alternate — that is the OK this gate exists to refuse"
    )


def test_plan_is_not_ok_without_a_mechanism(pre, status):
    report = {
        "prerequisite": {"ok": False, "why": "no destinations configured"},
        "alternate": {"ok": False, "via": None, "why": "no alternate"},
        "claimable": status.claimable(
            {"ok": False, "why": "no destinations configured"},
            {"ok": False, "via": None, "why": "no alternate"},
        ),
        "covered": [{"path": "/Users/me/wing", "holds": "ledger",
                     "snapshottable": True}],
        "uncovered": [{"path": "/Volumes/SSD1TB/nOS/data", "holds": "ssd",
                       "why": "HFS+", "snapshottable": False}],
        "recovery": status.RECOVERY,
    }
    result = pre.plan(report, dry_run=True, take=lambda c: {"taken": True})
    assert result["ok"] is False
    text = pre.render(result)
    assert "OK" not in text.split("\n")[0]
    assert "REFUSED" in text
    assert "/Users/me/wing" in text
    assert "/Volumes/SSD1TB/nOS/data" in text


def test_an_alternate_path_may_claim_a_net(pre, status):
    alt = {"ok": True, "via": "test-double", "why": "injected alternate"}
    claim = status.claimable({"ok": False, "why": "no destinations"}, alt)
    assert claim["ok"] is True and claim["via"] == "test-double"
    result = pre.plan(
        {"claimable": claim, "covered": [], "uncovered": [],
         "recovery": status.RECOVERY},
        dry_run=True, take=lambda c: {"taken": True},
    )
    assert result["ok"] is True
    assert "OK" in pre.render(result).split("\n")[0]


def test_tm_destination_may_claim_a_net(pre, status):
    claim = status.claimable(
        {"ok": True, "why": "a Time Machine destination is configured"},
        {"ok": False, "via": None, "why": "no alternate"},
    )
    assert claim["ok"] is True and claim["via"] == "tmutil-localsnapshot"
    result = pre.plan(
        {"claimable": claim, "covered": [], "uncovered": [],
         "recovery": status.RECOVERY},
        dry_run=True, take=lambda c: {"taken": True},
    )
    assert result["ok"] is True


def test_recovery_is_mount_apfs_copy_not_bootloader(status):
    text = status.RECOVERY.lower()
    assert "mount_apfs" in text
    assert "copy" in text
    assert "rdonly" in text or "read-only" in text or "-o rdonly" in status.RECOVERY
    assert "bless" not in text
    assert "not a bootloader" in text


def test_reader_prints_covered_versus_uncovered(status):
    """The reader, not the writer, is success. Covered and uncovered both land."""
    proc = subprocess.run(
        [sys.executable, str(STATUS)],
        cwd=REPO, capture_output=True, text=True, timeout=60, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "covered" in out.lower() and "uncovered" in out.lower()
    assert "Time Machine destination:" in out
    assert "recovery:" in out
    assert "mount_apfs" in out
    # Live estate: no TM dest, no alternate → capability is not yes.
    claim = status.claimable()
    if claim["ok"] is not True:
        assert "pre-converge snapshot capability: yes" not in out


def test_preflight_json_ok_tracks_claimable(pre):
    proc = subprocess.run(
        [sys.executable, str(PRE), "--dry-run", "--json"],
        cwd=REPO, capture_output=True, text=True, timeout=60, check=False,
    )
    data = json.loads(proc.stdout)
    claimable = data["claimable"]["ok"] is True
    assert data["ok"] is claimable
    if not claimable:
        assert proc.returncode == 1
        assert data["ok"] is False
