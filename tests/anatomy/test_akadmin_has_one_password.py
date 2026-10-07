"""akadmin's password is ONE derived leaf, everywhere it is declared.

Two registry leaves described the same credential (`akadmin` and
`authentik_admin`); the container booted with one and Infisical's nOS
Identity project stored the other, so the vault handed the operator a
password Authentik had never seen (2026-09-29, first v2 blank). Every
declaration must resolve through authentik_bootstrap_password.
"""
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import nos_identity as ni  # noqa: E402


def test_the_registry_has_one_leaf_for_akadmin():
    reg = yaml.safe_load((REPO / "files/anatomy/secrets/registry.yml").read_text())
    leaves = {k: v for k, v in reg["credentials"].items() if v.get("service") == "authentik" and "admin" in v.get("purpose", "")}
    assert list(leaves) == ["authentik_admin"], leaves


def test_every_declaration_routes_through_the_bootstrap_password():
    creds = (REPO / "default.credentials.yml").read_text()
    cfg = ni.default_config_text()
    assert "nos_derived_secrets.akadmin" not in creds + cfg
    assert 'akadmin_password: "{{ authentik_bootstrap_password }}"' in creds
    assert "akadmin_password | default(authentik_bootstrap_password)" in cfg
