"""Anatomy gate (P2-1) — OAuth2 provider grant_types are minimal + no ROPC.

Pins that the blueprint-RENDERED OAuth2 providers never mint a ``password``
(Resource Owner Password Credentials) grant — ROPC exchanges username+password
directly for tokens, bypassing the browser authorization flow AND any MFA stage.
Also pins the intended minimal grant sets:
  - 10-oidc-apps      → native_oidc providers: ['authorization_code','refresh_token']
  - 30-agent-clients  → M2M providers:        ['client_credentials']

NB this guards the RENDER only. The live forward_auth ProxyProviders carry a
``password`` grant stamped by upstream Authentik's ``ProxyProvider.set_oauth_defaults()``
(they are Django-MTI subclasses of OAuth2Provider) — that is upstream-owned and is
NOT a nOS render concern. Do NOT try to scrub it: a name-keyed delete would drop
the LIVE forward-auth provider (see the SSO review's refuted findings, 2026-06-02).

CI-safe: renders 10-oidc via the loader jinja env, source-scans 30-agent-clients;
no Docker / Authentik.
"""
from __future__ import annotations

import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
OIDC_J2 = REPO / "files/anatomy/plugins/authentik-base/blueprints/10-oidc-apps.yaml.j2"
AGENT_J2 = REPO / "roles/pazny.authentik/templates/blueprints/30-agent-clients.yaml.j2"
sys.path.insert(0, str(REPO / "files/anatomy"))

OAUTH2 = "authentik_providers_oauth2.oauth2provider"
_GRANT_BLOCK = re.compile(r"grant_types:\s*\n((?:\s*-\s*\"[^\"]+\"\s*\n)+)")


class _FindLoader(yaml.SafeLoader):
    pass


_FindLoader.add_constructor(
    "!Find", lambda loader, node: {"__Find__": loader.construct_sequence(node, deep=True)}
)
_FindLoader.add_multi_constructor("!", lambda loader, suffix, node: None)


def _env():
    from module_utils.load_plugins import _jinja_env  # noqa: WPS433

    return _jinja_env()


def _native_client() -> dict:
    return {
        "mode": "native_oidc",
        "client_id": "nos-grafana",
        "client_secret": "s",
        "slug": "grafana",
        "name": "Grafana",
        "tier": 1,
        "enabled": True,
        "redirect_uris": ["https://grafana.dev.local/login/generic_oauth"],
        "launch_url": "https://grafana.dev.local",
    }


def _oauth2_providers(rendered: str) -> list[dict]:
    doc = yaml.load(rendered, Loader=_FindLoader)
    return [e for e in (doc.get("entries") or []) if e.get("model") == OAUTH2 and "attrs" in e]


def test_10_oidc_native_grant_types_minimal_no_ropc():
    rendered = _env().from_string(OIDC_J2.read_text()).render(
        {"inputs": {"clients": [_native_client()]}, "authentik_oidc_apps": [], "tenant_domain": "dev.local"}
    )
    provs = _oauth2_providers(rendered)
    assert provs, "no oauth2provider rendered from 10-oidc-apps"
    for p in provs:
        gt = p["attrs"].get("grant_types")
        assert gt == ["authorization_code", "refresh_token"], (
            f"{p['identifiers']} grant_types must be [authorization_code, refresh_token], got {gt!r}"
        )
        assert "password" not in (gt or []), f"{p['identifiers']} must not mint a ROPC 'password' grant"


def test_30_agent_clients_grant_types_client_credentials_only():
    m = _GRANT_BLOCK.search(AGENT_J2.read_text())
    assert m, "30-agent-clients must declare an explicit grant_types block"
    items = re.findall(r'-\s*"([^"]+)"', m.group(1))
    assert items == ["client_credentials"], f"agent clients must be client_credentials-only, got {items}"


def test_no_ropc_password_grant_in_blueprint_sources():
    for f in (OIDC_J2, AGENT_J2):
        for m in _GRANT_BLOCK.finditer(f.read_text()):
            items = re.findall(r'-\s*"([^"]+)"', m.group(1))
            assert "password" not in items, f"{f.name} declares a ROPC 'password' grant — forbidden"
