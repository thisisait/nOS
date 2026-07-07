"""Increment 3c: the /upgrades macOS-as-managed-upgrade surface.

UpgradeRepository::osUpdateState() reads the ~/.nos continuation-plan.json (armed)
+ os-resume-result.json (last settle) sidecars; the presenter exposes them as
$osUpdate; default.latte renders an armed badge + a last-settle card, gated so an
absent sidecar renders nothing. Structural gates — the Wing runtime is exercised
by a live deploy, not here.
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WING = REPO / "files" / "anatomy" / "wing" / "app"
REPO_PHP = WING / "Model" / "UpgradeRepository.php"
PRESENTER = WING / "Presenters" / "UpgradesPresenter.php"
LATTE = WING / "Templates" / "Upgrades" / "default.latte"


def test_repository_reads_the_two_nos_sidecars():
    src = REPO_PHP.read_text()
    assert "function osUpdateState(" in src
    assert "continuation-plan.json" in src and "os-resume-result.json" in src
    # defensive read: HOME, is_file, json_decode with JsonException, object guard
    assert "function readNosObject(" in src
    assert "getenv('HOME')" in src and "is_file(" in src
    assert "JSON_THROW_ON_ERROR" in src and "JsonException" in src


def test_presenter_exposes_os_update():
    src = PRESENTER.read_text()
    assert "$this->template->osUpdate = $this->upgrades->osUpdateState()" in src


def test_latte_renders_armed_and_last_settle_gated():
    src = LATTE.read_text()
    # the whole card is gated on $osUpdate (absent sidecar → nothing renders)
    assert "{if $osUpdate !== null}" in src
    assert "upg-os-card" in src
    assert "$osUpdate['armed']" in src and "$osUpdate['last_settle']" in src
    # the last-settle card shows the os_before -> os_after transition + clean/warn
    assert "os_before" in src and "os_after" in src
    assert "is-clean" in src and "is-warn" in src
