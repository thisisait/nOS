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


def test_no_plugin_until_art30():
    assert not PLUGIN.exists(), (
        "device-gateway-base plugin would need a gdpr.legal_basis — that is "
        "an operator question (device-gdpr-art30), not an invented clause"
    )
    registry = REGISTRY.read_text(encoding="utf-8")
    assert "device-gateway" not in registry and "device_gateway" not in registry, (
        "do not add this service to tofu-authentik-services.yml — that map "
        "mints confidential authorization_code providers"
    )


def test_allowlist_excludes_pii_and_includes_roadmap():
    spec = ast.parse(GATEWAY.read_text(encoding="utf-8"))
    allow = None
    for node in spec.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "ALLOWLIST":
                    allow = ast.literal_eval(node.value)
    assert isinstance(allow, dict)
    assert "roadmap" in allow
    assert "current-state" in allow
    for banned in ("invoice", "party", "journal-entry", "account"):
        assert banned not in allow
    src = GATEWAY.read_text(encoding="utf-8")
    assert 'BIND = "127.0.0.1"' in src
    assert '["nos"' not in src and "nos dtt" not in src
    assert "KEAP_AGENT_TOKEN_RO" in src
    assert "RFC 8628" in src
    assert "userinfo" in src.lower()
    assert "AUTHENTIK_PUBLIC_O_BASE" in src
    assert "_token_is_for_this_client" in src
    assert "azp" in src
    assert not re.search(r'BIND\s*=\s*"0\.0\.0\.0"', src)
    assert "PyJWT" not in src and "cryptography" not in src


def test_tofu_escape_hatch_is_public_device_code():
    body = TOFU.read_text(encoding="utf-8")
    assert 'client_type = "public"' in body
    grants = re.search(r"grant_types\s*=\s*\[(.*?)\]", body, re.S)
    assert grants, "device_gateway.tf must declare grant_types"
    listed = re.findall(r'"([^"]+)"', grants.group(1))
    assert "urn:ietf:params:oauth:grant-type:device_code" in listed
    assert "refresh_token" in listed
    assert "password" not in listed
    assert "authorization_code" not in listed
    assert "count = var.install_device_gateway ? 1 : 0" in body
    assert 'slug               = "device-gateway"' in body
    tfvars = TFVARS.read_text(encoding="utf-8")
    assert "install_device_gateway" in tfvars
    vars_tf = (REPO / "terraform" / "authentik" / "variables.tf").read_text()
    assert 'variable "install_device_gateway"' in vars_tf
    chunk = vars_tf.split('variable "install_device_gateway"')[1][:400]
    assert "default     = false" in chunk


def test_plist_userinfo_is_loopback_and_device_urls_are_public():
    """Host daemon must not need the mkcert CA; handhelds must not see 127.0.0.1."""
    text = PLIST.read_text(encoding="utf-8")
    assert "AUTHENTIK_USERINFO_URL" in text
    assert "http://127.0.0.1:{{ authentik_port | default(9003) }}/application/o/userinfo/" in text
    assert "https://{{ authentik_domain }}/application/o/userinfo/" not in text
    assert "AUTHENTIK_PUBLIC_O_BASE" in text
    assert "https://{{ authentik_domain }}/application/o" in text


def test_userinfo_ok_is_not_enough_without_our_azp():
    """A Grafana token also gets userinfo 200; azp/aud must be nos-device-gateway."""
    import base64
    import importlib.util
    import json

    spec = importlib.util.spec_from_file_location("device_gateway", GATEWAY)
    gw = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gw)

    def mint(payload: dict) -> str:
        body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
        return f"h.{body}.s"

    assert gw._token_is_for_this_client(mint({"azp": "nos-device-gateway"}))
    assert gw._token_is_for_this_client(mint({"aud": "nos-device-gateway"}))
    assert gw._token_is_for_this_client(mint({"aud": ["nos-device-gateway", "other"]}))
    assert not gw._token_is_for_this_client(mint({"azp": "nos-grafana"}))
    assert not gw._token_is_for_this_client("not-a-jwt")
    assert not gw._token_is_for_this_client("a.b")
