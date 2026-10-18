"""Gate: the smoke catalog probes what this host installed, at this host's names.

Client host 2026-10-16, reinstalled on a core profile, tenant_domain jan.internal:
nos-smoke failed app_documenso/roundcube/twofauth at https://*.apps.dev.local/ —
apps_runner was off, and the probes came from a ~/.nos/smoke-catalog.runtime.yml
an earlier install had written with its own domain baked in.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
from nos_identity import installed  # noqa: E402

_spec = importlib.util.spec_from_file_location("nos_smoke_gate", REPO / "tools/nos-smoke.py")
smoke = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(smoke)

CORE = yaml.safe_load((REPO / "profiles/core.yml").read_text(encoding="utf-8"))
STALE = {"smoke_endpoints": [{"id": f"app_{a}", "url": f"https://{a}.apps.dev.local/", "tier": 2}
                             for a in ("documenso", "roundcube", "twofauth")]}


@pytest.fixture
def stale_home(tmp_path, monkeypatch):
    """A host whose earlier install left its runtime catalog behind."""
    (tmp_path / ".nos").mkdir()
    (tmp_path / ".nos/smoke-catalog.runtime.yml").write_text(yaml.safe_dump(STALE))
    monkeypatch.setenv("HOME", str(tmp_path))
    # Hermetic: nos-smoke reads the main checkout's config.yml, so the
    # operator's own toggles would leak into this gate.
    monkeypatch.setattr(smoke, "operator_file", lambda name: tmp_path / name)
    return tmp_path


def _catalog(**extra):
    v = smoke.load_vars(tenant_domain="jan.internal", overrides={**CORE, **extra})
    return v, smoke.build_catalog(v)


def test_core_profile_probes_only_installed_services(stale_home):
    v, entries = _catalog()
    on = {r["id"] for r in installed(v)}
    from_manifest = {e["id"] for e in entries if e["_source"] == "manifest"}
    assert from_manifest <= on, from_manifest - on
    assert not [e["id"] for e in entries if e["id"].startswith("app_")]


def test_every_url_is_under_the_resolved_domain(stale_home):
    _, entries = _catalog(apps_runner_enabled=True)
    hosts = {urlsplit(e["url"]).hostname for e in entries}
    stray = {h for h in hosts if h not in ("127.0.0.1", "localhost") and not h.endswith(".jan.internal")}
    assert not stray, stray


def test_installed_apps_are_probed_at_the_tenant_name(stale_home):
    _, entries = _catalog(apps_runner_enabled=True, host_alias="lab")
    urls = {e["id"]: e["url"] for e in entries}
    assert urls.get("app_documenso") == "https://documenso.lab.apps.jan.internal/"
