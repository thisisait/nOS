"""Device gateway slice 1: default-OFF, loopback, allowlist, no nos dtt.

The handheld prototype bound 0.0.0.0 and called `nos dtt` (human KEAP door).
The estate role is default-OFF, Traefik-skipped, 127.0.0.1, and talks to the
agent surface with KEAP_AGENT_TOKEN_RO. Forward-auth is the wrong gate.
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


def test_install_flag_defaults_off():
    text = DEFAULTS.read_text(encoding="utf-8")
    assert re.search(r"^install_device_gateway:\s*false\b", text, re.M), (
        "install_device_gateway must default false — do not ship LAN-open"
    )


def test_import_role_is_gated_on_the_flag():
    text = MAIN.read_text(encoding="utf-8")
    assert "pazny.device_gateway" in text
    assert "install_device_gateway | default(false)" in text


def test_manifest_id_is_skipped_at_traefik():
    services = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))["services"]
    row = next(s for s in services if s["id"] == "device_gateway")
    assert row["install_flag"] == "install_device_gateway"
    assert row.get("domain_var") and row.get("port_var")
    raw = re.sub(r"\{\{[^}]+\}\}", "TEMPLATE", TRAEFIK.read_text(encoding="utf-8"))
    skipped = set((yaml.safe_load(raw) or {}).get("traefik_skip_ids") or [])
    assert "device_gateway" in skipped, (
        "device_gateway must stay in traefik_skip_ids until RFC 8628 — "
        "authentik@file is the wrong gate for a device"
    )


def test_new_graph_nodes_are_withheld():
    text = RULING.read_text(encoding="utf-8")
    assert '"service:device_gateway": withheld' in text
    assert '"daemon:eu.thisisait.nos.device-gateway": withheld' in text


def test_no_plugin_until_art30():
    assert not PLUGIN.exists(), (
        "device-gateway-base plugin would need a gdpr.legal_basis — that is "
        "an operator question (device-gdpr-art30), not an invented clause"
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
