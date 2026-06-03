"""Anatomy gate (REM-043) — n8n SSRF protection is wired + on by default.

n8n's HTTP Request node + webhooks could scan the internal Docker network
(no-auth peers) — the unauthenticated SSRF amplifier for SEC-02. n8n ships
instance-wide SSRF protection since 2.12 (default-OFF upstream); nOS enables it
default-ON, with the built-in RFC-1918+loopback block set (covers every nOS peer)
and an opt-in allowlist escape hatch.

Pins: (1) the plugin compose-ext gates N8N_SSRF_PROTECTION_ENABLED on
n8n_ssrf_protection (default true); (2) the invented N8N_WEBHOOK_AUTH (which the
remediation queue once recommended, but does NOT exist upstream and is the inbound
receiver not the SSRF egress vector) never appears; (3) defaults ship it on.

CI-safe: source scan; no Docker.
"""
from __future__ import annotations

import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
COMPOSE_EXT = REPO / "files/anatomy/plugins/n8n-base/templates/n8n-base.compose.yml.j2"
DEFAULTS = REPO / "roles/pazny.n8n/defaults/main.yml"


def test_ssrf_env_wired_and_gated():
    src = COMPOSE_EXT.read_text()
    assert "N8N_SSRF_PROTECTION_ENABLED" in src, "n8n SSRF protection env not wired"
    assert "n8n_ssrf_protection | default(true)" in src, (
        "SSRF env must be gated on n8n_ssrf_protection (default true)"
    )


def test_no_invented_webhook_auth_env():
    src = COMPOSE_EXT.read_text()
    assert "N8N_WEBHOOK_AUTH" not in src, (
        "N8N_WEBHOOK_AUTH does not exist upstream (it's the inbound receiver, not the "
        "SSRF egress vector) — do not invent it"
    )


def test_defaults_enable_ssrf_protection():
    src = DEFAULTS.read_text()
    assert "n8n_ssrf_protection: true" in src, "n8n_ssrf_protection must default true"
    assert "n8n_ssrf_allowed_hostnames" in src, "the allowlist escape-hatch var must exist"
