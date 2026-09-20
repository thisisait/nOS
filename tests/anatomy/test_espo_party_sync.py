"""espo-party-sync — KEAP party → Espo Account payload, no network."""
from __future__ import annotations

import importlib.util
import pathlib
import subprocess

REPO = pathlib.Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location(
        "espo_party_sync", REPO / "tools" / "espo-party-sync.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_join_tag_format_is_nos_party_slug():
    mod = _load()
    assert mod.MARKER == "nos:party:"
    p = mod.account_payload({"slug": "party-ico-25596641", "legal_name": "Buyer s.r.o.",
                             "role": "client", "notes": "VAT payer"})
    assert p["description"].endswith("nos:party:party-ico-25596641")
    assert p["description"].startswith("VAT payer")
    assert p["type"] == "Customer"


def test_account_payload_defaults_partner_when_not_client():
    mod = _load()
    p = mod.account_payload({"slug": "party-supplier-1", "party_kind": "supplier"})
    assert p["name"] == "party-supplier-1"
    assert p["description"] == "nos:party:party-supplier-1"
    assert p["type"] == "Partner"


def test_docker_env_empty_when_docker_missing(monkeypatch):
    mod = _load()

    def boom(*_a, **_k):
        raise OSError("no docker")

    monkeypatch.setattr(mod.subprocess, "run", boom)
    assert mod._docker_env("ESPOCRM_SITE_URL") == ""


def test_docker_env_reads_printenv_stdout(monkeypatch):
    mod = _load()

    def fake_run(cmd, **_k):
        assert cmd[:4] == ["docker", "exec", "espocrm", "printenv"]
        return subprocess.CompletedProcess(cmd, 0, stdout="https://espocrm.apps.dev.local/\n", stderr="")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    assert mod._docker_env("ESPOCRM_SITE_URL") == "https://espocrm.apps.dev.local/"


def test_espo_base_url_prefers_env_over_docker(monkeypatch):
    mod = _load()
    monkeypatch.setenv("ESPO_URL", "https://override.example/")
    monkeypatch.setattr(mod, "_docker_env", lambda *_a, **_k: "https://from-docker/")
    assert mod.espo_base_url() == "https://override.example"


def test_espo_base_url_autowires_from_docker(monkeypatch):
    mod = _load()
    monkeypatch.delenv("ESPO_URL", raising=False)
    monkeypatch.setattr(
        mod, "_docker_env",
        lambda key, container=None: "https://espocrm.apps.dev.local/" if key == "ESPOCRM_SITE_URL" else "")
    assert mod.espo_base_url() == "https://espocrm.apps.dev.local"


def test_auth_headers_autowire_bootstrap_admin_from_docker(monkeypatch):
    mod = _load()
    for k in ("ESPO_API_KEY", "ESPO_ADMIN_PASSWORD", "ESPO_API_USER"):
        monkeypatch.delenv(k, raising=False)

    def env(key, container=None):
        return {
            "ESPOCRM_ADMIN_PASSWORD": "from-compose",
            "ESPOCRM_ADMIN_USERNAME": "admin",
        }.get(key, "")

    monkeypatch.setattr(mod, "_docker_env", env)
    h = mod.espo_auth_headers()
    assert h["Authorization"].startswith("Basic ")
    assert "X-Api-Key" not in h


def test_auth_headers_prefer_api_key(monkeypatch):
    mod = _load()
    monkeypatch.setenv("ESPO_API_KEY", "k")
    monkeypatch.setenv("ESPO_API_USER", "admin")
    h = mod.espo_auth_headers()
    assert h["X-Api-Key"] == "k"
    assert "Authorization" not in h


def test_auth_headers_use_bootstrap_admin_password(monkeypatch):
    mod = _load()
    monkeypatch.delenv("ESPO_API_KEY", raising=False)
    monkeypatch.setenv("ESPO_ADMIN_PASSWORD", "secret")
    monkeypatch.setenv("ESPO_API_USER", "admin")
    h = mod.espo_auth_headers()
    assert h["Authorization"].startswith("Basic ")
    assert "X-Api-Key" not in h
