"""Gate: the e2e plan probes a Pulse job only if the catalog would register it.

MEASURED 2026-11-02 on a fresh Ubuntu host converged `-e @profiles/core.yml`:
four `<job>-registered-in-wing` probes read red (loop:propose, discovery,
alert-relay, invoice-vision). Wing was right — the catalog had dropped them.
The plan was wrong twice: e2e.enabled said `install_wing` where the catalog
reads requires.feature_flag + peers, and state.yml never recorded the run's
install_loops=false, so every reader saw the default true.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import nos_identity as ni  # noqa: E402

_spec = importlib.util.spec_from_file_location("e2e_plan_jobs", REPO / "tools/e2e-plan.py")
plan_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(plan_mod)
CATALOG = REPO / "files/anatomy/scripts/discover-pulse-catalog.py"


def _installed_jobs(flags: dict) -> set[str]:
    env = {**os.environ, "NOS_PLAYBOOK_DIR": str(REPO), "NOS_INSTALL_FLAGS": json.dumps(flags)}
    out = subprocess.run([sys.executable, str(CATALOG)], capture_output=True, text=True, env=env, check=True)
    return {f"{j['plugin_name'].removesuffix('-base')}:{j['job']['name']}"
            for j in json.loads(out.stdout) if j["installed"]}


def _probed_jobs(rows: list[dict]) -> set[str]:
    return {key.split(".", 1)[1].rsplit(".id", 1)[0]
            for r in rows for p in r["probes"]
            for key in ((p.get("expect") or {}).get("json_equals") or {}) if key.startswith("jobs.")}


@pytest.mark.parametrize("profile", ["core.yml", "all-on.yml"])
def test_every_probed_job_is_one_the_catalog_registers(profile):
    layers = ni.profile_layers(REPO / "profiles" / profile)
    flags = ni.install_flags(layers)
    vars_ = {**plan_mod.smoke.merge_config(*layers), **flags, "tenant_domain": "example.test"}
    stray = _probed_jobs(plan_mod.plan(vars_)) - _installed_jobs(flags)
    assert not stray, f"{profile}: the plan probes jobs the catalog drops: {sorted(stray)}"


def test_the_run_records_its_install_flags_and_the_plan_reads_them(tmp_path, monkeypatch):
    role_vars = {"install_loops": False, "install_wing": "true", "install_x": "{{ y }}",
                 "bone_secret": "never-copied"}
    state = tmp_path / "state.yml"
    _nos_state_module()._action_introspect(_Module(), {"manifest_path": str(REPO / "state/manifest.yml"),
                                                       "state_path": str(state), "role_vars": role_vars})
    rec = yaml.safe_load(state.read_text()).get("flags")
    assert rec == {"install_loops": False, "install_wing": True}, "bools of install_* only, never a template"
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("NOS_STATE_FILE", str(state))
    monkeypatch.setattr(plan_mod.smoke, "operator_file", lambda name: tmp_path / name)
    assert "loop:propose" not in _probed_jobs(plan_mod.plan()), "-e install_loops=false is what ran"


class _Module:
    check_mode = False

    def fail_json(self, **kw):
        raise AssertionError(kw)

    def exit_json(self, **kw):
        pass


def _nos_state_module():
    sys.path.insert(0, str(REPO / "files/anatomy"))
    spec = importlib.util.spec_from_file_location("nos_state_mod", REPO / "files/anatomy/library/nos_state.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
