"""Dolibarr is a role+plugin CRM desk; SSO is honest forward_auth.

RETRO-RED: before pazny.dolibarr / dolibarr-base landed these paths
did not exist. Espo harvest stays off (`apps/espocrm.yml.draft`).
"""

from __future__ import annotations

import pathlib
import re

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
PLUGIN = REPO / "files/anatomy/plugins/dolibarr-base/plugin.yml"
COMPOSE = REPO / "roles/pazny.dolibarr/templates/compose.yml.j2"
DEFAULTS = REPO / "default.config.yml"
PRAXIS = REPO / "profiles/praxis.yml"
KEAP = REPO / "files/anatomy/plugins/keap-base/plugin.yml"
TRAEFIK = REPO / "roles/pazny.traefik/vars/main.yml"
STACK_UP = REPO / "tasks/stacks/stack-up.yml"
MAIN = REPO / "main.yml"
REGISTRY = REPO / "files/anatomy/secrets/registry.yml"
MANIFEST = REPO / "state/manifest.yml"


def test_dolibarr_plugin_is_forward_auth_until_oidc_is_proven():
    man = yaml.safe_load(PLUGIN.read_text(encoding="utf-8"))
    assert man["name"] == "dolibarr-base"
    assert man["requires"]["feature_flag"] == "install_dolibarr"
    assert man["requires"]["role"] == "pazny.dolibarr"
    assert man["authentik"]["mode"] == "forward_auth"
    assert man["authentik"]["slug"] == "dolibarr"
    assert man["gdpr"]["legal_basis"] == "contract"
    ups = [d["upstream"] for d in man.get("depends_on") or []]
    assert "service:mariadb" in ups


def test_dolibarr_compose_uses_shared_mariadb_not_an_embedded_db():
    src = COMPOSE.read_text(encoding="utf-8")
    assert "DOLI_DB_HOST" in src
    assert "mariadb" in src
    assert "dolibarr/dolibarr" in src
    assert "gated_b2b_net" in src
    assert 'DOLI_DB_SSL: "false"' in src
    assert "mariadb_client_ca_path" not in src
    assert "DOLI_ENABLE_MODULES" in src
    assert "embedded" not in src.lower() or "not an embedded" in src.lower()


def test_dolibarr_backup_dirs_have_restore_targets():
    cfg = DEFAULTS.read_text(encoding="utf-8")
    assert 'name: "dolibarr-documents"' in cfg
    assert 'name: "dolibarr-custom"' in cfg
    restore = (REPO / "tasks/restore.yml").read_text(encoding="utf-8")
    assert "dolibarr-documents:" in restore
    assert "dolibarr-custom:" in restore


def test_install_dolibarr_defaults_off_and_praxis_turns_it_on():
    raw = DEFAULTS.read_text(encoding="utf-8")
    m = re.search(r"^install_dolibarr:\s*(\S+)", raw, re.M)
    assert m and m.group(1).startswith("false")
    prof = yaml.safe_load(PRAXIS.read_text(encoding="utf-8")) or {}
    assert prof.get("install_dolibarr") is True


def test_keap_does_not_schedule_the_retired_espo_party_sync():
    text = KEAP.read_text(encoding="utf-8")
    assert "keap-espo-party-sync" not in text
    assert "espo-party-sync" not in text


def test_dolibarr_is_wired_through_stack_traefik_manifest_and_mariadb_autodep():
    stack = STACK_UP.read_text(encoding="utf-8")
    assert "pazny.dolibarr" in stack
    assert "install_dolibarr" in stack
    tv = yaml.safe_load(TRAEFIK.read_text(encoding="utf-8"))
    assert tv["traefik_auth_modes"]["dolibarr"] == "proxy"
    man = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    row = next(s for s in man["services"] if s["id"] == "dolibarr")
    assert row["install_flag"] == "install_dolibarr"
    assert row["oidc"] == "proxy"
    main = MAIN.read_text(encoding="utf-8")
    assert "install_dolibarr" in main
    secrets = REGISTRY.read_text(encoding="utf-8")
    assert "oidc_dolibarr:" in secrets
    assert "dolibarr_admin:" in secrets
