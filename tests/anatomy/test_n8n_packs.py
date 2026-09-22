"""n8n pack contract (docs/doctrine/n8n-packs.md §8)."""
from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
TOOL = REPO / "tools" / "n8n-pack.py"
PACKS = REPO / "files/anatomy/n8n/packs"
COMPOSE = REPO / "roles/pazny.n8n/templates/compose.yml.j2"
COMPOSE_EXT = REPO / "files/anatomy/plugins/n8n-base/templates/n8n-base.compose.yml.j2"
PLUGIN = REPO / "files/anatomy/plugins/n8n-base/plugin.yml"
SECRETS = REPO / "templates/secrets.yml.j2"
DEFAULTS = REPO / "roles/pazny.n8n/defaults/main.yml"


def _mod():
    spec = importlib.util.spec_from_file_location("n8n_pack", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_pack_lint_is_clean():
    proc = subprocess.run(
        [sys.executable, str(TOOL), "lint", "--packs", str(PACKS)],
        cwd=REPO, capture_output=True, text=True, timeout=10)
    assert proc.returncode == 0, proc.stderr


def test_encryption_key_adopts_volume_config(tmp_path):
    secrets = tmp_path / "secrets.yml"
    cfg = tmp_path / "config"
    cfg.write_text(json.dumps({"encryptionKey": "adopted-from-volume-key-32xx"}), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(TOOL), "encryption-key",
         "--secrets", str(secrets), "--config", str(cfg)],
        capture_output=True, text=True, timeout=10)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "adopted-from-volume-key-32xx"
    assert "adopted" in proc.stderr
    again = subprocess.run(
        [sys.executable, str(TOOL), "encryption-key",
         "--secrets", str(secrets), "--config", str(cfg)],
        capture_output=True, text=True, timeout=10)
    assert again.stdout.strip() == "adopted-from-volume-key-32xx"
    assert "reused" in again.stderr


def test_render_refuses_loopback_keap():
    mod = _mod()
    wf = {"nodes": [{"parameters": {"url": "http://127.0.0.1:8091/agent/v1/x"}}]}
    try:
        mod.render_workflow(wf, "http://127.0.0.1:8091", None)
    except SystemExit:
        return
    raise AssertionError("loopback KEAP base must be refused")


def test_compose_carries_managed_encryption_key():
    src = COMPOSE.read_text(encoding="utf-8")
    assert "N8N_ENCRYPTION_KEY" in src
    assert "n8n_encryption_key" in src
    assert "n8n_encryption_key:" in SECRETS.read_text(encoding="utf-8")
    assert "n8n_api_key:" in SECRETS.read_text(encoding="utf-8")


def test_ssrf_defaults_stay_empty_but_keap_pack_path_allowlists():
    """The KEAP pack path re-opens the host-gateway addresses through the guard.

    IP RANGES, not hostnames — and the reason is read from the shipped source,
    not guessed (both measured 2026-09-21): N8N_SSRF_ALLOWED_HOSTNAMES exists
    but covers only the lookup phase; the connect-time validator sees a bare
    IP (ssrf-protection.service.js validateConnectionHost), so a
    hostname-only allowlist still blocked the pack write. And the lookup
    phase validates EVERY resolved address, so the /etc/hosts IPv6
    host-gateway row blocks a v4-only range list — the default must carry
    both families. This gate refuses the hostname-only spelling because it
    is INSUFFICIENT, not fictional."""
    defaults = DEFAULTS.read_text(encoding="utf-8")
    assert 'n8n_ssrf_allowed_ip_ranges: ""' in defaults
    # GLOBAL, not a role default: the plugin loader renders the compose
    # extension without role defaults in scope (a role-scoped var came out "").
    config = (REPO / "default.config.yml").read_text(encoding="utf-8")
    assert "n8n_host_gateway_cidr" in config
    assert "n8n_host_gateway_cidr:" not in defaults, "must be global-only (loader scope)"
    ext = COMPOSE_EXT.read_text(encoding="utf-8")
    assert "install_keap" in ext and "n8n_host_gateway_cidr" in ext
    assert "N8N_SSRF_ALLOWED_IP_RANGES" in ext
    assert "N8N_SSRF_ALLOWED_HOSTNAMES" not in ext, (
        "hostname allowlist is lookup-phase only — the connect-time IP "
        "validator ignores it; use IP ranges")
    # both address families, or the /etc/hosts v6 row re-blocks the pack path
    assert "192.168.65.254/32" in config and "::254/128" in config


def test_n8n_base_watch_is_not_a_clock():
    text = PLUGIN.read_text(encoding="utf-8")
    assert "exec-watch" in text
    assert "n8n-fire.py" not in text
    assert "secret:n8n_api_key" in text
    assert "ares-verify-base" in (REPO / "files/anatomy/plugins/ares-verify-base/plugin.yml").read_text()
