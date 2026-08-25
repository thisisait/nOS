"""A matrix row must know its security floor, or "at target" is a lie.

WHAT HAPPENED (2026-08-25, upgrade-architect run 8c52551a). REM-159 sat
pending CRITICAL: the running GitLab 18.11.9-ce.0 inside CVE-2026-19478
(CVSS 9.4, unauthenticated), security_floor 19.2.4-ce.0. The architect's
whole brief is the matrix — it repaired gitlab's stale target to the
installed version, correct for what it could see, and made the row read "at
target" for a service under an unauthenticated 9.4. The agent did nothing
wrong; THE WIRING withheld the number. The fix is in the matrix, not the
agent's prompt: anything not in the matrix does not exist for any matrix
consumer (architect, advisor, the /upgrades page, the operator), and a
prompt fix would have repaired exactly one of them.

WHAT IS PINNED.
  - remediation_items carries security_floor (schema + ALTER sweep + ingest),
    because fix_version is prose nothing can compare against.
  - UpgradeRepository::securityPosture() — pure, static, DB-free like
    compareVersions — folds pending rows into {pending_ids, max_severity,
    floor, below_floor}, with below_floor NULL (unknown) rather than false
    when the comparison refuses.
  - matrix() attaches it to every row, and an unreadable queue surfaces as
    {unavailable: true}, never as "no findings".
  - The architect's brief names below_floor as a gap class that "at target"
    does not close.

PROVEN IN THE BROKEN DIRECTION by running this file against the pre-change
tree: every functional test errors (securityPosture absent) and every
structural assert fails (no security key, no floor column, no ingest bind).

WHAT IT CANNOT SEE. Whether the live wing.db has re-run init-db + the ingest
(that is the converge's job), and whether a consumer reads the field.
"""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
REPOSITORY = REPO / "files/anatomy/wing/app/Model/UpgradeRepository.php"
INIT_DB = REPO / "files/anatomy/wing/bin/init-db.php"
INGEST = REPO / "files/anatomy/wing/bin/ingest-remediation.php"
PROFILE = REPO / "files/anatomy/agents/upgrade-architect.yml"


def _php() -> str | None:
    return shutil.which("php")


def _posture(installed, rows) -> dict | None:
    script = (
        f'require "{REPOSITORY}";'
        'echo json_encode(App\\Model\\UpgradeRepository::securityPosture('
        f"{json.dumps(installed)}, json_decode('{json.dumps(rows)}', true)));"
    )
    out = subprocess.run(["php", "-r", script], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


REM_159 = {"id": "REM-159", "severity": "CRITICAL", "security_floor": "19.2.4-ce.0"}


@pytest.mark.skipif(_php() is None, reason="php absent — the fold cannot run")
def test_rem_159_the_measured_case_reads_below_floor():
    """The exact row the 2026-08-25 run could not see."""
    got = _posture("18.11.9-ce.0", [REM_159])
    assert got["below_floor"] is True, got
    assert got["max_severity"] == "CRITICAL"
    assert got["floor"] == "19.2.4-ce.0"
    assert got["pending_ids"] == ["REM-159"]


@pytest.mark.skipif(_php() is None, reason="php absent")
def test_at_or_past_the_floor_is_not_below_it():
    assert _posture("19.2.4-ce.0", [REM_159])["below_floor"] is False
    assert _posture("19.3.0-ce.0", [REM_159])["below_floor"] is False


@pytest.mark.skipif(_php() is None, reason="php absent")
def test_unknown_is_null_never_false():
    """No floor recorded, or an uncomparable pin, must NOT read as safe."""
    no_floor = _posture("2.5.0", [{"id": "REM-001", "severity": "MEDIUM",
                                   "security_floor": None}])
    assert no_floor["below_floor"] is None and no_floor["max_severity"] == "MEDIUM"
    uncomparable = _posture("sha-b9a80dc", [REM_159])
    assert uncomparable["below_floor"] is None, (
        "a build-id pin compared against a version floor claimed a boolean — "
        "the comparison must refuse, and refusal is UNKNOWN, not false")


@pytest.mark.skipif(_php() is None, reason="php absent")
def test_the_worst_row_wins():
    got = _posture("1.0.0", [
        {"id": "REM-A", "severity": "LOW", "security_floor": "1.1.0"},
        {"id": "REM-B", "severity": "HIGH", "security_floor": "2.0.0"},
    ])
    assert got["max_severity"] == "HIGH"
    assert got["floor"] == "2.0.0", "the HIGHEST floor governs, not the first"
    assert got["below_floor"] is True
    assert _posture("1.0.0", []) is None, "no pending rows = nothing to say"


def test_matrix_rows_carry_the_posture_and_honest_unavailability():
    src = REPOSITORY.read_text(encoding="utf-8")
    body = src[src.index("public function matrix()"):]
    assert "securityPosture" in body and "'security'" in body, (
        "matrix() no longer attaches the security posture — every consumer "
        "is back to the 2026-08-25 blindness")
    assert "'unavailable' => true" in body, (
        "an unreadable remediation mirror must surface as unavailable on the "
        "row; silently omitting it renders as 'no findings', which is green")


def test_the_floor_column_exists_end_to_end():
    init = INIT_DB.read_text(encoding="utf-8")
    assert "security_floor" in init.split("remediation_items", 1)[1].split(")\",", 1)[0], (
        "remediation_items CREATE TABLE lost security_floor")
    assert "'security_floor' => 'TEXT'" in init, (
        "the idempotent ALTER sweep lost security_floor — pre-existing DBs "
        "never gain the column and the matrix join dies on them")
    ingest = INGEST.read_text(encoding="utf-8")
    assert ":floor" in ingest and "security_floor     = excluded.security_floor" in ingest, (
        "ingest-remediation.php no longer carries security_floor from the "
        "queue JSON — the column exists but stays NULL for ever")
    assert "security_floor  IS NOT excluded.security_floor" in ingest, (
        "the change-guard ignores security_floor — a floor edit in the queue "
        "would not propagate on re-sync")


def test_the_architects_brief_names_the_gap_class():
    src = PROFILE.read_text(encoding="utf-8")
    assert "below_floor" in src and "security.floor" in src, (
        "the architect's brief no longer names the below-floor gap class — "
        "the matrix would carry the number and the agent would not act on it")
