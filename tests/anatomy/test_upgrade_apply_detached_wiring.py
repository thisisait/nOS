"""Phase-4: plan -> detached wiring + Bone session_risk refuse.

- Bone `apply()` REFUSES a session_risk (host_app/host_reboot) recipe with 409 +
  a detached hint. Bone runs the playbook with no TTY, so the engine's session-
  risk pause would hang; and attached is exactly the risk. The operator's path
  for such a recipe is apply-detached.
- `apply_detached()` + the /apply-detached route + the Wing chain
  (UpgradeRepository::applyDetached -> Api actionApplyDetached -> router) exist so
  a run_mode=detached choice actually launches nos-upgrade-detached.sh.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
BONE = REPO / "files" / "anatomy" / "bone"
WING = REPO / "files" / "anatomy" / "wing" / "app"


@pytest.fixture()
def bone_upgrades(tmp_path, monkeypatch):
    import sys  # noqa: PLC0415

    monkeypatch.syspath_prepend(str(BONE))
    # Bone's upgrades.py and its siblings (`import migrations`, `import state`)
    # share bare top-level names with the test packages tests/upgrades/,
    # tests/migrations/, tests/state_manager→state. Once pytest collects those,
    # they shadow sys.modules, so bone's `import upgrades`/`import migrations`
    # resolve to the TEST packages (no UPGRADES_DIR / invoke_playbook). Drop the
    # cached names so syspath_prepend(BONE) above resolves each to files/anatomy/
    # bone/*.py (monkeypatch restores sys.modules after the test).
    for _name in ("upgrades", "migrations", "state"):
        monkeypatch.delitem(sys.modules, _name, raising=False)
    try:
        import upgrades  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"bone upgrades not importable standalone: {exc}")
    if not hasattr(upgrades, "UPGRADES_DIR"):  # collision guard (should not trigger)
        pytest.skip("resolved a non-Bone 'upgrades' module (name collision)")
    (tmp_path / "demo.yml").write_text(textwrap.dedent("""\
        service: demo
        recipes:
          - id: demo-hr-1-to-2
            from_regex: '^1\\.'
            to: '2.0.0'
            severity: breaking
            reset: {scope: host_reboot, reason: needs a reboot}
          - id: demo-c-1-to-2
            from_regex: '^1\\.'
            to: '2.0.1'
            severity: minor
            reset: {scope: container, reason: just a bump}
    """))
    monkeypatch.setattr(upgrades, "UPGRADES_DIR", tmp_path)
    return upgrades


def test_apply_refuses_session_risk_recipe(bone_upgrades):
    res = bone_upgrades.apply("demo", "demo-hr-1-to-2")
    assert res.get("status") == 409, res
    assert res.get("scope") == "host_reboot"
    assert "apply-detached" in res.get("hint", "")


def test_apply_allows_container_recipe(bone_upgrades, monkeypatch):
    # a container recipe is NOT session_risk → apply() proceeds past the refuse.
    # Stub invoke_playbook so no ansible actually runs.
    import migrations as migrate_mod  # noqa: PLC0415
    monkeypatch.setattr(migrate_mod, "invoke_playbook",
                        lambda *a, **k: {"returncode": 0, "output": "stub"})
    res = bone_upgrades.apply("demo", "demo-c-1-to-2")
    assert res.get("applied") is True and res.get("status") is None


def test_bone_apply_detached_is_wired():
    src = (BONE / "upgrades.py").read_text()
    assert "def apply_detached(" in src
    assert "nos-upgrade-detached.sh" in src
    assert '_SESSION_RISK_SCOPES = ("host_app", "host_reboot")' in src
    main = (BONE / "main.py").read_text()
    assert "/apply-detached" in main and "apply_detached(" in main
    assert 'require_scope("nos:upgrades:apply")' in main


def test_wing_detached_chain_exists():
    assert "function applyDetached(" in (WING / "Model" / "UpgradeRepository.php").read_text()
    assert "/apply-detached" in (WING / "Model" / "UpgradeRepository.php").read_text()
    assert "actionApplyDetached(" in (WING / "Presenters" / "Api" / "UpgradesPresenter.php").read_text()
    router = (WING / "Core" / "RouterFactory.php").read_text()
    # the apply-detached route must precede the generic <service>/<recipe> catch-all
    assert "apply-detached" in router
    assert router.index("apply-detached") < router.index("Upgrades:recipe")
