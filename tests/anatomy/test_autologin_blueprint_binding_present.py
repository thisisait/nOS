"""Anatomy gate — autologin authorization_flow binding (Batch 5 REVERTED).

REVERTED 2026-06-01 (live-validated failure): the Batch-5 ``nos-autologin-flow``
was a broken *authorization* flow (built as a Dummy-stage carrier with no
provider-authorization stage). Authentik rejected every provider bound to it
with "Invalid grant_type for provider" / "The request is otherwise malformed",
breaking OIDC login for ALL autologin native_oidc services (grafana, gitlab,
gitea, nextcloud, HA…). Browser-confirmed: Jellyfin (``supports: no`` → stock
flow) worked while every ``nos-autologin-flow``-bound client failed. The plan
flagged this exact risk (GH #15814 implicit-consent silent-skip).

Back-out: ``60-autologin-flow.yaml.j2`` deleted; ``10-oidc-apps.yaml.j2`` binds
EVERY client to the stock ``default-provider-authorization-implicit-consent``.
Service-side force-OIDC (Batch 1-3 env/config) still delivers autologin — only
the consent-screen-skip polish (which broke authorization) is gone.

This gate pins the revert so the broken custom flow cannot creep back:
  1. No ``60-autologin-flow.yaml.j2`` blueprint exists.
  2. ``10-oidc-apps.yaml.j2`` binds providers ONLY to implicit-consent — never
     ``nos-autologin-flow`` — regardless of a client's ``autologin.enabled``.

Render strategy: reuse the production loader env factory
(``module_utils.load_plugins._jinja_env``) so the render — including the Ansible
``bool`` filter shim and ChainableUndefined — is byte-identical to the live
blueprint render path.
"""

from __future__ import annotations

import pathlib
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
BLUEPRINTS = REPO / "files" / "anatomy" / "plugins" / "authentik-base" / "blueprints"
OIDC_J2 = BLUEPRINTS / "10-oidc-apps.yaml.j2"
FLOW_J2 = BLUEPRINTS / "60-autologin-flow.yaml.j2"

IMPLICIT_CONSENT = "default-provider-authorization-implicit-consent"
AUTOLOGIN_FLOW = "nos-autologin-flow"

sys.path.insert(0, str(REPO / "files" / "anatomy"))


class _FindLoader(yaml.SafeLoader):
    """SafeLoader tolerant of Authentik's ``!Find [model, [k, v]]`` tags."""


_FindLoader.add_constructor(
    "!Find",
    lambda loader, node: {"__Find__": loader.construct_sequence(node, deep=True)},
)


def _env():
    from module_utils.load_plugins import _jinja_env  # noqa: WPS433 (lazy)

    return _jinja_env()


def _render_oidc(clients: list[dict]) -> str:
    tmpl = _env().from_string(OIDC_J2.read_text())
    return tmpl.render(
        {
            "inputs": {"clients": clients},
            "authentik_oidc_apps": [],
            "tenant_domain": "dev.local",
        }
    )


def _authz_flows(rendered: str) -> list[str]:
    """Every provider's authorization_flow slug in the rendered blueprint."""
    doc = yaml.load(rendered, Loader=_FindLoader)
    out: list[str] = []
    for e in doc["entries"]:
        if e.get("model") in (
            "authentik_providers_oauth2.oauth2provider",
            "authentik_providers_proxy.proxyprovider",
        ):
            find = e["attrs"].get("authorization_flow", {}).get("__Find__")
            if find:
                assert find[0] == "authentik_flows.flow"
                out.append(find[1][1])
    return out


def _native_client(enabled) -> dict:
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
        "autologin": {
            "supports": "yes",
            "enabled": enabled,
            "hides_local_form": True,
            "break_glass": "?disableAutoLogin=true",
        },
    }


# ── The revert is pinned ───────────────────────────────────────────────────


def test_autologin_flow_blueprint_removed():
    """The broken custom authorization flow must stay deleted."""
    assert not FLOW_J2.exists(), (
        f"{FLOW_J2.name} reintroduces the broken nos-autologin-flow that returned "
        "'Invalid grant_type for provider' and broke OIDC for every bound client "
        "(see module docstring). Keep it removed."
    )


def test_oidc_binds_only_implicit_consent():
    """No client — autologin-enabled or not — may bind nos-autologin-flow.

    Exercises both the Python-bool and the loader's pre-rendered string shapes
    of ``autologin.enabled``; every authorization_flow must resolve to the stock
    implicit-consent flow.
    """
    for enabled in (True, False, "True", "False"):
        flows = _authz_flows(_render_oidc([_native_client(enabled)]))
        assert flows, f"no provider rendered (enabled={enabled!r})"
        assert AUTOLOGIN_FLOW not in flows, (
            f"client (autologin.enabled={enabled!r}) bound to the reverted "
            f"{AUTOLOGIN_FLOW}; it must use {IMPLICIT_CONSENT}"
        )
        assert all(f == IMPLICIT_CONSENT for f in flows), (
            f"expected every authorization_flow to be {IMPLICIT_CONSENT}, got {flows}"
        )
