"""Anatomy CI gate — Phase 2 plan-choice run_mode + reset-scope persistence.

Pins the write path from docs/archive/upgrade-reset-scope-and-session-safety.md
(§"Wing /upgrades surface", §"Run mode"):

  - UpgradeRepository::planUpgradeWithMode accepts a $runMode param, validates it
    against {attached, detached, stage_then_reboot} (anything else → 'attached'),
    resolves the recipe's authored reset block, and persists reset_scope +
    session_risk (RECOMPUTED from scope, never client-trusted) + run_mode onto the
    queued upgrades_planned row.
  - UpgradesPresenter::actionPlanChoice reads run_mode from the POST (default
    'attached'), passes it to the repo, and folds run_mode + reset_scope into the
    plan_choice_recorded audit payload.

Static source assertions catch a regression even where php is unavailable; the
functional fresh-DB build (skipped if php/sqlite3 is missing) proves the columns
round-trip the way the repo writes them.
"""
from __future__ import annotations

import pathlib
import shutil
import sqlite3
import subprocess
import tempfile

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
MODEL = REPO / "files/anatomy/wing/app/Model"
PRESENTERS = REPO / "files/anatomy/wing/app/Presenters"
INITDB = REPO / "files/anatomy/wing/bin/init-db.php"

RUN_MODES = ["attached", "detached", "stage_then_reboot"]


# ── Repository write path ──────────────────────────────────────────────────

def test_plan_upgrade_with_mode_accepts_run_mode_param():
    """planUpgradeWithMode gains a $runMode param (default 'attached')."""
    src = (MODEL / "UpgradeRepository.php").read_text()
    assert "function planUpgradeWithMode" in src, "planUpgradeWithMode missing"
    assert "string $runMode = 'attached'" in src, (
        "planUpgradeWithMode must accept $runMode defaulting to 'attached'"
    )


def test_plan_upgrade_with_mode_validates_run_mode_closed_set():
    """An invalid run_mode falls back to 'attached' (closed-set validation)."""
    src = (MODEL / "UpgradeRepository.php").read_text()
    assert "in_array($runMode, ['attached', 'detached', 'stage_then_reboot'], true)" in src, (
        "planUpgradeWithMode must validate $runMode against the closed set"
    )
    assert "? $runMode : 'attached'" in src, (
        "an invalid run_mode must fall back to 'attached'"
    )


def test_plan_upgrade_with_mode_persists_reset_scope_session_risk_run_mode():
    """The queued-row UPDATE stamps reset_scope + session_risk + run_mode."""
    src = (MODEL / "UpgradeRepository.php").read_text()
    assert "'reset_scope'    => $resetScope" in src, "must persist reset_scope"
    assert "'session_risk'   => $sessionRisk ? 1 : 0" in src, (
        "must persist session_risk as 0/1"
    )
    assert "'run_mode'       => $runMode" in src, "must persist run_mode"


def test_session_risk_recomputed_server_side_not_trusted():
    """session_risk is RECOMPUTED from the resolved scope (decodeReset), never
    read from a client-supplied bool."""
    src = (MODEL / "UpgradeRepository.php").read_text()
    assert "function resetForRecipe" in src, (
        "must resolve the recipe's reset server-side (resetForRecipe)"
    )
    assert "$reset = $this->resetForRecipe($service, $recipeId)" in src, (
        "planUpgradeWithMode must resolve reset via resetForRecipe"
    )
    assert "$sessionRisk = $reset['session_risk']" in src, (
        "session_risk must come from the resolved reset, not the request body"
    )
    # resetForRecipe decodes via the same decodeReset the matrix uses.
    assert "$this->decodeReset(" in src


# ── Presenter read path ────────────────────────────────────────────────────

def test_presenter_reads_run_mode_and_defaults_attached():
    """actionPlanChoice reads run_mode from the POST, validating to 'attached'."""
    src = (PRESENTERS / "UpgradesPresenter.php").read_text()
    assert "function actionPlanChoice" in src, "actionPlanChoice missing"
    assert "$req->getPost('run_mode')" in src, "must read run_mode from POST"
    assert "in_array($runMode, ['attached', 'detached', 'stage_then_reboot'], true)" in src, (
        "presenter must validate run_mode against the closed set"
    )
    assert "? $runMode : 'attached'" in src, "invalid run_mode must default 'attached'"


def test_presenter_passes_run_mode_to_repo():
    """actionPlanChoice forwards $runMode to planUpgradeWithMode."""
    src = (PRESENTERS / "UpgradesPresenter.php").read_text()
    assert "$this->upgrades->planUpgradeWithMode(" in src
    # the trailing $runMode arg reaches the repo call.
    call = src[src.index("$this->upgrades->planUpgradeWithMode("):]
    call = call[:call.index(");") + 2]
    assert "$runMode" in call, "run_mode must be passed to planUpgradeWithMode"


def test_audit_payload_carries_run_mode_and_reset_scope():
    """plan_choice_recorded folds run_mode + reset_scope into the result map."""
    src = (PRESENTERS / "UpgradesPresenter.php").read_text()
    assert "'run_mode'               => $runMode" in src, (
        "audit payload must carry run_mode"
    )
    assert "'reset_scope'            => $result['reset_scope']" in src, (
        "audit payload must carry reset_scope"
    )


# ── Functional proof: the columns round-trip on a fresh wing.db ─────────────

@pytest.mark.skipif(
    shutil.which("php") is None, reason="php unavailable — skip live DB build"
)
def test_fresh_db_round_trips_run_mode_reset_scope_session_risk():
    """A fresh init-db'd wing.db persists the Phase 2 columns the way
    planUpgradeWithMode writes them: a queued row carrying run_mode +
    reset_scope + session_risk."""
    with tempfile.TemporaryDirectory(prefix="wing-p2-") as tmp:
        proc = subprocess.run(
            ["php", str(INITDB), f"--data-dir={tmp}"],
            capture_output=True, text=True,
        )
        assert proc.returncode == 0, f"init-db.php failed: {proc.stderr}"
        con = sqlite3.connect(str(pathlib.Path(tmp) / "wing.db"))
        try:
            cols = {r[1] for r in con.execute("PRAGMA table_info(upgrades_planned)")}
            for c in ("reset_scope", "session_risk", "run_mode"):
                assert c in cols, f"upgrades_planned missing column: {c}"

            con.execute(
                "INSERT INTO upgrades_planned"
                "(service,recipe_id,status,plan_mode,reset_scope,session_risk,run_mode) "
                "VALUES('postgresql','16-to-17','planned','migration','stack',1,'stage_then_reboot')"
            )
            con.commit()
            row = con.execute(
                "SELECT reset_scope, session_risk, run_mode FROM upgrades_planned "
                "WHERE service='postgresql'"
            ).fetchone()
            assert row == ("stack", 1, "stage_then_reboot"), (
                f"Phase 2 columns did not round-trip: {row}"
            )

            # The run_mode column DEFAULTs to 'attached' for a plain insert.
            con.execute(
                "INSERT INTO upgrades_planned(service,recipe_id,status) "
                "VALUES('grafana','g-r','planned')"
            )
            con.commit()
            dflt = con.execute(
                "SELECT run_mode, session_risk FROM upgrades_planned WHERE service='grafana'"
            ).fetchone()
            assert dflt[0] == "attached", "run_mode must DEFAULT 'attached'"
            assert dflt[1] == 0, "session_risk must DEFAULT 0"
        finally:
            con.close()
