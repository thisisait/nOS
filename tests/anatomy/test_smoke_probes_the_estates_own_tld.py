"""nos-smoke in a bare worktree must probe the estate's resolved universe.

The loop engine judges an EPHEMERAL worktree that never contains the
gitignored config.yml, so the judge's nos-smoke rendered the default
`dev.local` while the estate served `pazny.eu` — every probe 404'd and gate
set `live` failed every bound ceremony on the wrong universe (judge run
81dd74b6, 2026-08-29: 28 probes, all FAIL, while the operator's own run said
47/47 OK). With the tld alone fixed, the worktree re-run still failed 2/28 on
mailpit + superset — services the operator's config.yml DISABLES, probed
because the sandbox saw only the defaults. The runtime sidecar records both
resolved answers: `instance.tld` and `services.<id>.enabled`.

Runs the real function from tools/nos-smoke.py, not a description of it.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

STATE = """\
instance:
  tld: pazny.eu
services:
  mailpit:
    enabled: false
  superset:
    enabled: false
  code_server:
    enabled: true
  no_flag_recorded:
    stack: iiab
"""

MANIFEST = {"services": [{"id": "code_server", "install_flag": "install_code_server"}]}


def _smoke():
    spec = importlib.util.spec_from_file_location("nos_smoke", str(ROOT / "tools" / "nos-smoke.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["nos_smoke"] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _vars():
    return {
        "tenant_domain": "dev.local",
        "install_mailpit": True,          # the default the sandbox would see
        "install_superset": True,
        "install_code_server": False,
    }


def test_bare_worktree_resolves_tld_and_enablement_from_the_sidecar(tmp_path):
    smoke = _smoke()
    state = tmp_path / "state.yml"
    state.write_text(STATE)
    v = _vars()
    smoke.apply_runtime_estate_fallback(v, tmp_path / "no-config.yml", state, MANIFEST)
    assert v["tenant_domain"] == "pazny.eu"
    assert v["install_mailpit"] is False, (
        "the estate disabled mailpit; probing it 404s and fails the judge "
        "on a service that is OFF on purpose"
    )
    assert v["install_superset"] is False
    assert v["install_code_server"] is True, (
        "manifest install_flag mapping lost — an enabled service stays unprobed"
    )
    assert "install_no_flag_recorded" not in v, "invented a flag nothing declares"


def test_an_operator_checkout_with_config_yml_is_untouched(tmp_path):
    smoke = _smoke()
    config = tmp_path / "config.yml"
    config.write_text("tenant_domain: operator.example\n")
    state = tmp_path / "state.yml"
    state.write_text(STATE)
    v = _vars()
    before = dict(v)
    v["tenant_domain"] = "operator.example"
    smoke.apply_runtime_estate_fallback(v, config, state, MANIFEST)
    assert v["tenant_domain"] == "operator.example", (
        "config.yml is the operator's declaration; the sidecar must not outrank it"
    )
    assert v["install_mailpit"] is before["install_mailpit"]


def test_no_sidecar_and_no_config_changes_nothing(tmp_path):
    smoke = _smoke()
    v = _vars()
    before = dict(v)
    smoke.apply_runtime_estate_fallback(v, tmp_path / "no-config.yml", tmp_path / "no-state.yml", MANIFEST)
    assert v == before
