"""nos-smoke in a bare worktree must probe the estate's resolved tld.

The loop engine judges an EPHEMERAL worktree that never contains the
gitignored config.yml, so the judge's nos-smoke rendered the default
`dev.local` while the estate served `pazny.eu` — every probe 404'd and gate
set `live` failed every bound ceremony on the wrong universe (judge run
81dd74b6, 2026-08-29: 28 probes, all FAIL, while the operator's own run said
47/47 OK). The runtime sidecar's `instance.tld` is the estate's resolved
answer and is what the fallback must read.

Runs the real function from tools/nos-smoke.py, not a description of it.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _smoke():
    spec = importlib.util.spec_from_file_location("nos_smoke", str(ROOT / "tools" / "nos-smoke.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["nos_smoke"] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_bare_worktree_takes_the_tld_from_the_runtime_sidecar(tmp_path):
    smoke = _smoke()
    state = tmp_path / "state.yml"
    state.write_text("instance:\n  tld: pazny.eu\n")
    v = {"tenant_domain": "dev.local"}
    smoke.apply_runtime_tld_fallback(v, tmp_path / "no-config.yml", state)
    assert v["tenant_domain"] == "pazny.eu"


def test_an_operator_checkout_with_config_yml_is_untouched(tmp_path):
    smoke = _smoke()
    config = tmp_path / "config.yml"
    config.write_text("tenant_domain: operator.example\n")
    state = tmp_path / "state.yml"
    state.write_text("instance:\n  tld: pazny.eu\n")
    v = {"tenant_domain": "operator.example"}
    smoke.apply_runtime_tld_fallback(v, config, state)
    assert v["tenant_domain"] == "operator.example", (
        "config.yml is the operator's declaration; the sidecar must not outrank it"
    )


def test_no_sidecar_and_no_config_changes_nothing(tmp_path):
    smoke = _smoke()
    v = {"tenant_domain": "dev.local"}
    smoke.apply_runtime_tld_fallback(v, tmp_path / "no-config.yml", tmp_path / "no-state.yml")
    assert v["tenant_domain"] == "dev.local"
