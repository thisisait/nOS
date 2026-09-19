"""Dispositions live beside the generated queue, not inside it.

sec-queue-authorship: the scanner regenerates remediation-queue.json and
drops resolved_by. scan-dispositions-sidecar: a sidecar the scanner never
opens; rem-status joins at read time. Not dtt — a finding is not a work row.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
REM = REPO / "tools/rem-status.py"
DISPOSE = REPO / "tools/rem-dispose.py"


def _env(tmp: Path) -> dict[str, str]:
    return {**os.environ, "NOS_SECURITY_DIR": str(tmp), "VULNSCAN_SECURITY_DIR": str(tmp)}


def _write_queue(tmp: Path, items: list[dict]) -> None:
    (tmp / "remediation-queue.json").write_text(
        json.dumps({"generated_at": "2026-09-16T00:00:00Z", "items": items}) + "\n",
        encoding="utf-8",
    )


def _write_sidecar(tmp: Path, by_id: dict[str, dict]) -> None:
    (tmp / "dispositions.json").write_text(
        json.dumps(by_id) + "\n", encoding="utf-8",
    )


def _status(tmp: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(REM), *args],
        env=_env(tmp), capture_output=True, text=True, check=True,
    )


def test_sidecar_resolved_wins_over_pending_notebook(tmp_path):
    _write_queue(tmp_path, [{
        "id": "REM-249", "status": "pending", "severity": "HIGH",
        "component": "rustfs", "scan_cycle": 50,
    }])
    _write_sidecar(tmp_path, {
        "REM-249": {
            "status": "resolved",
            "resolved_by": "SOURCE e617a4ad",
            "resolved_at": "2026-09-16T18:40:00+02:00",
        }
    })
    raw = json.loads(_status(tmp_path, "--json").stdout)
    pending_ids = [i["id"] for i in raw["pending"]]
    assert "REM-249" not in pending_ids, (
        "sidecar resolved_by did not join — rem-status still lists the "
        f"generated pending row: {pending_ids}"
    )
    assert raw["by_status"].get("resolved") == 1


def test_a_scan_shaped_rewrite_does_not_drop_the_sidecar(tmp_path):
    """The scanner rewrites the notebook without disposition keys."""
    _write_queue(tmp_path, [{
        "id": "REM-249", "status": "pending", "severity": "HIGH",
        "component": "rustfs", "scan_cycle": 51,
        # no resolved_by — this is what the nightly regenerate looks like
    }])
    _write_sidecar(tmp_path, {
        "REM-249": {"status": "resolved", "resolved_by": "kept"}
    })
    raw = json.loads(_status(tmp_path, "--json").stdout)
    assert raw["by_status"].get("resolved") == 1
    assert raw["by_status"].get("pending", 0) == 0


def test_closed_without_sidecar_evidence_stays_unproven(tmp_path):
    _write_queue(tmp_path, [{
        "id": "REM-001", "status": "resolved", "severity": "HIGH",
        "component": "x", "scan_cycle": 1,
    }])
    raw = json.loads(_status(tmp_path, "--json").stdout)
    assert raw["unproven_closures"] == 1


def test_rem_status_is_a_reader_not_a_writer():
    src = REM.read_text(encoding="utf-8")
    assert ".write_text" not in src


def test_rem_dispose_writes_the_sidecar_not_the_notebook(tmp_path):
    _write_queue(tmp_path, [{
        "id": "REM-250", "status": "pending", "severity": "HIGH",
        "component": "freescout", "scan_cycle": 50,
    }])
    proc = subprocess.run(
        [sys.executable, str(DISPOSE), "REM-250", "--status", "resolved",
         "--by", "pin 2.2.8"],
        env=_env(tmp_path), capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    notebook = json.loads((tmp_path / "remediation-queue.json").read_text())
    assert notebook["items"][0]["status"] == "pending", (
        "rem-dispose mutated the generated notebook — the scanner would "
        "fight it every night"
    )
    sidecar = json.loads((tmp_path / "dispositions.json").read_text())
    assert sidecar["REM-250"]["status"] == "resolved"
    assert sidecar["REM-250"]["resolved_by"] == "pin 2.2.8"
    raw = json.loads(_status(tmp_path, "--json").stdout)
    assert raw["by_status"].get("resolved") == 1
