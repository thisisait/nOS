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


def test_the_drift_hook_counts_the_joined_queue(tmp_path):
    """drift-watch and NosCriticalCveFound* read this hook's count. Unjoined, it
    paged 4 CRITICAL on 2026-10-04 while rem-status showed 2."""
    hook = REPO / "hooks/playbook-end.d/20-cve-drift-check.sh"
    _write_queue(tmp_path, [
        {"id": "REM-256", "status": "pending", "severity": "CRITICAL"},
        {"id": "REM-264", "status": "pending", "severity": "CRITICAL"},
    ])
    (tmp_path / "scan-state.json").write_text('{"components": {}}\n', encoding="utf-8")
    _write_sidecar(tmp_path, {"REM-256": {"status": "resolved", "resolved_by": "x"}})
    out = subprocess.run(
        ["bash", str(hook)], env={**_env(tmp_path), "TEXTFILE_DIR": str(tmp_path)},
        capture_output=True, text=True, check=True,
    ).stdout
    assert json.loads(out)["pending_critical"] == 1, out


def test_discovery_scan_judges_the_joined_queue(tmp_path, monkeypatch):
    """Probe B read the raw notebook while rem-status read the join. On
    2026-10-07 five rows (REM-156/244/251/253/260) were resolved in the sidecar
    and still reported `still pending` — two readers, one fact, two answers."""
    import importlib.util

    _write_queue(tmp_path, [{
        "id": "REM-156", "status": "pending", "severity": "HIGH",
        "component": "nodered", "fix_version": "4.1.13",
    }])
    _write_sidecar(tmp_path, {"REM-156": {"status": "resolved", "resolved_by": "pin 4.1.14"}})
    monkeypatch.setenv("NOS_SECURITY_DIR", str(tmp_path))
    monkeypatch.setenv("VULNSCAN_SECURITY_DIR", str(tmp_path))
    spec = importlib.util.spec_from_file_location(
        "discovery_scan_join", REPO / "tools/discovery-scan.py")
    scan = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = scan
    spec.loader.exec_module(scan)
    res = scan.ScanResult()
    scan.probe_queue_vs_running({"iiab-nodered-1": "nodered/node-red:4.1.14"}, res)
    assert not res.findings, [f.title for f in res.findings]
    assert "obs-queue-rem-156" in res.judged


def test_discovery_scan_dispose_line_is_shell_safe(tmp_path, monkeypatch):
    """The copy-paste `tools/rem-dispose.py ...` line was hand-quoted with
    `\"`; an image or name holding `"`, `$(` or a backtick printed a line the
    shell would read differently from what the probe meant."""
    import importlib.util
    import shlex

    _write_queue(tmp_path, [{
        "id": "REM-156", "status": "pending", "severity": "HIGH",
        "component": "nodered", "fix_version": "4.1.13",
    }])
    monkeypatch.setenv("NOS_SECURITY_DIR", str(tmp_path))
    monkeypatch.setenv("VULNSCAN_SECURITY_DIR", str(tmp_path))
    spec = importlib.util.spec_from_file_location(
        "discovery_scan_quote", REPO / "tools/discovery-scan.py")
    scan = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = scan
    spec.loader.exec_module(scan)
    res = scan.ScanResult()
    name, image = "iiab-nodered-1", 'evil"$(id)`x`/node-red:4.1.14'
    scan.probe_queue_vs_running({name: image}, res)
    assert len(res.findings) == 1, [f.title for f in res.findings]
    line = next(ln for ln in res.findings[0].body.splitlines()
                if "tools/rem-dispose.py" in ln)
    line = line[line.index("tools/rem-dispose.py"):]
    assert shlex.split(line) == [
        "tools/rem-dispose.py", "REM-156", "--status", "resolved",
        "--by", f"discovery-scan: {name} runs {image} >= 4.1.13",
    ]
