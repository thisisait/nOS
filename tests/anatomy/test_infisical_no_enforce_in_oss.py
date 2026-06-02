"""Anatomy gate — Infisical CE is a gate-only forward_auth service (no OIDC).

CORRECTED 2026-06-02 (live-verified on the running v0.159.16): Infisical's
org-level OIDC SSO is an ENTERPRISE-licensed feature. On a CE plan the OIDC_*
env that the plugin used to seed is INERT — verified live: `oidc_configs` table
= 0 rows, `/api/v1/sso/redirect/oidc` = 404, and an unauthenticated GET of the
vault host returned 200 (NO Authentik gate). That left a Tier-1 vault ungated
behind a false `native_oidc` promise.

New contract (gate-only — Authentik gates ACCESS via authentik@file, then
Infisical shows its own email/password form):
  1. plugin authentik.mode == forward_auth (NOT native_oidc).
  2. NO authentik.autologin block (forward_auth = pure access gate; also pinned
     by test_no_autologin_for_pure_proxy_services).
  3. the compose-extension renders NO dead OIDC_* org-SSO env (and never an
     enterprise enforce token) — re-adding it does nothing on CE and re-opens
     the ungated-vault hole.
  4. infisical is in the `proxy` Traefik auth bucket (so the authentik@file
     middleware actually gates it), NOT `oidc`.
"""

from __future__ import annotations

import pathlib
import re

import yaml

# tests/conftest.py adds files/anatomy/ to sys.path.
from module_utils import load_plugins  # type: ignore  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[2]
PLUGIN_DIR = REPO / "files" / "anatomy" / "plugins" / "infisical-base"
PLUGIN_YML = PLUGIN_DIR / "plugin.yml"
COMPOSE_EXT = PLUGIN_DIR / "templates" / "infisical-base.compose.yml.j2"
TRAEFIK_VARS = REPO / "roles" / "pazny.traefik" / "vars" / "main.yml"

# Any OIDC org-SSO / enterprise-enforce token that must NOT reach a CE render.
_FORBIDDEN_ENV_TOKENS = (
    "oidc_client_id",
    "oidc_client_secret",
    "oidc_discovery_url",
    "oidc_issuer",
    "oidc_redirect_uri",
    "authenforced",
    "enforce_oidc",
    "oidc_enforce",
)

_FORCE_ON_CTX = {
    "install_authentik": True,
    "sso_autologin": True,
    "sso_autologin_infisical": True,
    "sso_autologin_min_tier_1": True,
    "global_password_prefix": "nos",
    "tenant_domain": "dev.local",
    "infisical_domain": "vault.dev.local",
    "infisical_port": 8080,
}


def _strip_comments(line: str) -> str:
    line = re.sub(r"\{#.*?#\}", "", line)
    idx = line.find("#")
    return line[:idx] if idx != -1 else line


def _render_compose_ext() -> str:
    rendered = load_plugins._render_string(COMPOSE_EXT.read_text(), dict(_FORCE_ON_CTX))
    return "\n".join(_strip_comments(ln) for ln in rendered.splitlines())


def test_infisical_is_forward_auth_not_native_oidc():
    data = yaml.safe_load(PLUGIN_YML.read_text()) or {}
    a = data.get("authentik") or {}
    assert a.get("mode") == "forward_auth", (
        "Infisical CE cannot do org-OIDC (enterprise-licensed) → must be forward_auth "
        f"(gate-only), not {a.get('mode')!r} — else the Tier-1 vault is ungated."
    )


def test_infisical_has_no_autologin_block():
    data = yaml.safe_load(PLUGIN_YML.read_text()) or {}
    a = data.get("authentik") or {}
    assert "autologin" not in a, (
        "forward_auth Infisical must carry NO autologin block (pure access gate; "
        "CE has no OIDC to force/seed)."
    )


def test_infisical_compose_ext_renders_no_dead_oidc_env():
    rendered = _render_compose_ext().lower()
    hits = [tok for tok in _FORBIDDEN_ENV_TOKENS if tok in rendered]
    assert not hits, (
        "infisical compose-extension rendered OIDC/enforce env that is INERT on CE "
        f"and re-opens the ungated-vault lie: {hits}. Gate at the edge instead."
    )


def test_infisical_is_in_proxy_auth_bucket():
    vars_doc = yaml.safe_load(TRAEFIK_VARS.read_text()) or {}
    modes = vars_doc.get("traefik_auth_modes") or {}
    assert modes.get("infisical") == "proxy", (
        "infisical must be in the 'proxy' Traefik auth bucket so authentik@file "
        f"forward-auth actually gates the vault; got {modes.get('infisical')!r}."
    )
