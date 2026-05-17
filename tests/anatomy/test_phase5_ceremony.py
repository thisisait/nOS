"""Anatomy gate for the operator-driven Phase 5 ceremony CLI.

Pins the contract of `tools/run-phase5-ceremony.sh` — pre-flight probes,
env-resolution-from-DB strategy, post-flight verifier, markdown report.
"""

from __future__ import annotations

import pathlib
import stat
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / "tools/run-phase5-ceremony.sh"


def test_phase5_script_present_and_executable():
    assert SCRIPT.is_file()
    mode = SCRIPT.stat().st_mode
    assert mode & stat.S_IXUSR, "run-phase5-ceremony.sh must be chmod +x"


def test_phase5_script_passes_bash_lint():
    """Catches accidentally-introduced syntax errors."""
    result = subprocess.run(
        ["bash", "-n", str(SCRIPT)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"bash -n failed: {result.stderr}"


def test_phase5_script_probes_required_surfaces():
    """Pre-flight contract — Bone /api/health + pulse_jobs row + dep check."""
    src = SCRIPT.read_text()
    # Bone health probe + configurable URL.
    assert "/api/health" in src
    assert "BONE_API_URL" in src
    # pulse_jobs lookup against the conductor self-test job ID pattern.
    assert "pulse_jobs" in src
    assert "self-test-001" in src
    # Dep guards for the script's own commands.
    for cmd in ("sqlite3", "curl", "jq", "python3"):
        assert cmd in src, f"missing dep guard for {cmd}"


def test_phase5_script_reads_env_from_pulse_jobs_row():
    """Resolution strategy: env_json from wing.db.pulse_jobs (Ansible already
    rendered the operator-specific prefix), not from re-reading config.yml.
    """
    src = SCRIPT.read_text()
    assert "env_json" in src
    # Resolved env vars become real exports before the subprocess call.
    assert "export " in src
    # PULSE_RUN_ID override so manual runs are distinguishable from scheduled.
    assert "PULSE_RUN_ID=" in src
    assert "phase5-manual-" in src


def test_phase5_script_verifies_wing_db_after_run():
    """Post-flight contract — events + notifications delta + actor_action_id."""
    src = SCRIPT.read_text()
    assert "EVENT_DELTA" in src
    assert "NOTIF_DELTA" in src
    assert "actor_action_id" in src
    # Conductor-attributed reads.
    assert "source = 'conductor'" in src
    assert "origin_agent = 'conductor'" in src


def test_phase5_script_emits_markdown_report():
    src = SCRIPT.read_text()
    # Markdown structure pinned for downstream tooling (operator + Wing /audit
    # link follow-up).
    assert "# Phase 5 ceremony report" in src
    assert "## Pre-flight" in src
    assert "## Post-flight" in src
    assert "## Verdict" in src
    # Green = exit 0 AND ≥2 events written (start + end pair at minimum).
    assert '"$EVENT_DELTA" -ge 2' in src
    assert "**GREEN**" in src
    assert "**RED**" in src


def test_phase5_script_supports_dry_run():
    """--dry-run skips the actual subprocess invocation."""
    src = SCRIPT.read_text()
    assert "--dry-run" in src
    assert "DRY_RUN" in src


def test_phase5_script_handles_empty_args_array_under_set_u():
    """Regression: pulse_jobs.args_json can be `[]` — under `set -u` the
    bare `${arr[@]}` expansion errors. The fix uses `${arr[@]+...}` so the
    empty case is allowed.
    """
    src = SCRIPT.read_text()
    assert "JOB_ARGS_ARR[@]+" in src
