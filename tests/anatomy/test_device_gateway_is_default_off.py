"""Device gateway: default-OFF, loopback, RFC 8628, ungated Traefik (ntfy class).

The handheld prototype bound 0.0.0.0 and called `nos dtt` (human KEAP door).
The estate role is default-OFF, 127.0.0.1, KEAP_AGENT_TOKEN_RO. Traefik routes
device.<tld> with auth_mode none — authentik@file 302s a machine caller.
"""
from __future__ import annotations

import ast
import pathlib
import re

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
GATEWAY = REPO / "files" / "anatomy" / "device-gateway" / "gateway.py"
DEFAULTS = REPO / "default.config.yml"
MAIN = REPO / "main.yml"
MANIFEST = REPO / "state" / "manifest.yml"
TRAEFIK = REPO / "roles" / "pazny.traefik" / "vars" / "main.yml"
RULING = REPO / "files" / "anatomy" / "apex" / "ruling.yml"
PLUGIN = REPO / "files" / "anatomy" / "plugins" / "device-gateway-base"
TOFU = REPO / "terraform" / "authentik" / "device_gateway.tf"
TFVARS = REPO / "templates" / "tofu" / "nos.auto.tfvars.json.j2"
PLIST = REPO / "roles" / "pazny.device_gateway" / "templates" / "device-gateway.plist.j2"
REGISTRY = REPO / "state" / "tofu-authentik-services.yml"


def _traefik() -> dict:
    raw = re.sub(r"\{\{[^}]+\}\}", "TEMPLATE", TRAEFIK.read_text(encoding="utf-8"))
    return yaml.safe_load(raw) or {}


def test_install_flag_defaults_off():
    text = DEFAULTS.read_text(encoding="utf-8")
    assert re.search(r"^install_device_gateway:\s*false\b", text, re.M), (
        "install_device_gateway must default false — do not ship LAN-open"
    )


def test_import_role_is_gated_on_the_flag():
    text = MAIN.read_text(encoding="utf-8")
    assert "pazny.device_gateway" in text
    assert "install_device_gateway | default(false)" in text


def test_manifest_id_is_routed_ungated_with_justification():
    services = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))["services"]
    row = next(s for s in services if s["id"] == "device_gateway")
    assert row["install_flag"] == "install_device_gateway"
    assert row.get("domain_var") and row.get("port_var")
    tvars = _traefik()
    skipped = set(tvars.get("traefik_skip_ids") or [])
    assert "device_gateway" not in skipped, (
        "device_gateway must leave traefik_skip_ids so Traefik routes device.<tld> "
        "— authentik@file is still the wrong gate; mode is none"
    )
    assert tvars.get("traefik_auth_modes", {}).get("device_gateway") == "none"
    reason = (tvars.get("traefik_auth_none_justification") or {}).get("device_gateway", "")
    assert len(reason.strip()) >= 40, "REM-144: a comment is not a justification"
    for needle in ("machine caller", "authentik@file", "userinfo", "allowlist", "127.0.0.1"):
        assert needle in reason, f"justification missing {needle!r}"


def test_new_graph_nodes_are_withheld():
    text = RULING.read_text(encoding="utf-8")
    assert '"service:device_gateway": withheld' in text
    assert '"daemon:eu.thisisait.nos.device-gateway": withheld' in text


def test_plugin_is_the_art30_row_not_an_oidc_client():
    """The plugin exists for its gdpr block (2026-10-02); it must not mint a
    second provider — device_gateway.tf owns the RFC 8628 public client."""
    manifest = yaml.safe_load((PLUGIN / "plugin.yml").read_text(encoding="utf-8"))
    assert manifest.get("gdpr", {}).get("legal_basis"), "device-gateway-base carries the Art-30 row"
    assert "authentik" not in manifest, "no authentik: block — the tofu file is the client"
    registry = REGISTRY.read_text(encoding="utf-8")
    assert "device-gateway" not in registry and "device_gateway" not in registry, (
        "do not add this service to tofu-authentik-services.yml — that map "
        "mints confidential authorization_code providers"
    )
