"""Anatomy gate — autologin → nos-autologin-flow blueprint binding.

sso-autologin-plan.md §"Testy / gates":

  > `test_autologin_blueprint_binding_present`: `10-oidc-apps.yaml.j2`:
  > `autologin.enabled` true → `authorization_flow` = `nos-autologin-flow`,
  > jinak byte-identický s dneškem.

And §"Vazba na Authentik branding" (Batch 5): a dedicated `nos-autologin-flow`
blueprint (Dummy stage + per-flow background + Custom CSS — NO custom stage
class, NO image bloat) that `autologin: true` clients route their
`authorization_flow` at INSTEAD of the stock
`default-provider-authorization-implicit-consent`.

This gate pins TWO things:

  1. The blueprint `60-autologin-flow.yaml.j2` exists, renders, safe_loads,
     declares the `nos-autologin-flow` flow + a Dummy stage carrier, and carries
     NO consent stage (the implicit-consent variant the plan recommends IF the
     operator verifies silent-skip — GH #15814/#13068/#8660). NO custom stage
     class (no Python plugin into the Authentik image). NO inlined base64 image
     (the branded splash is a per-flow `background` path, not image bloat).

  2. `10-oidc-apps.yaml.j2` switches `authorization_flow` to `nos-autologin-flow`
     ONLY for a client whose `autologin.enabled` resolves true; for an
     autologin-off / no-autologin-block / forward_auth proxy client it is
     byte-identical to today (`default-provider-authorization-implicit-consent`).

Render strategy: reuse the production loader env factory
(`module_utils.load_plugins._jinja_env`) so the render — including the Ansible
`bool` filter shim and ChainableUndefined — is byte-identical to the live
blueprint render path (the loader's render_dir, the SOLE renderer for these two
files; the role only templates 00/30). The aggregator pre-renders
`authentik.autologin.enabled` to a bool-ish STRING via _deep_render, so both the
Python-bool and the string ("True"/"False") shapes are exercised.
"""

from __future__ import annotations

import pathlib
import sys

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
BLUEPRINTS = REPO / "files" / "anatomy" / "plugins" / "authentik-base" / "blueprints"
OIDC_J2 = BLUEPRINTS / "10-oidc-apps.yaml.j2"
FLOW_J2 = BLUEPRINTS / "60-autologin-flow.yaml.j2"

IMPLICIT_CONSENT = "default-provider-authorization-implicit-consent"
AUTOLOGIN_FLOW = "nos-autologin-flow"

# Make the loader's module_utils importable the same way the codebase does
# (PYTHONPATH=files/anatomy). The env factory carries the Ansible filter shim
# (incl. `bool`) so the render matches production.
sys.path.insert(0, str(REPO / "files" / "anatomy"))


class _FindLoader(yaml.SafeLoader):
    """SafeLoader that tolerates Authentik's `!Find [model, [k, v]]` tags so a
    rendered blueprint round-trips through yaml.safe_load. The tag body is kept
    as a plain dict {'__Find__': [...]} for assertion."""


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


def _authz_flow_slug(rendered: str, *, proxy: bool) -> str:
    doc = yaml.load(rendered, Loader=_FindLoader)
    model = (
        "authentik_providers_proxy.proxyprovider"
        if proxy
        else "authentik_providers_oauth2.oauth2provider"
    )
    providers = [e for e in doc["entries"] if e.get("model") == model]
    assert providers, f"no {model} entry rendered"
    find = providers[0]["attrs"]["authorization_flow"]["__Find__"]
    # !Find [authentik_flows.flow, [slug, <slug>]] → ['authentik_flows.flow', ['slug', '<slug>']]
    assert find[0] == "authentik_flows.flow"
    return find[1][1]


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


# ── 1. The blueprint itself ───────────────────────────────────────────────


def test_autologin_flow_blueprint_exists_and_renders():
    assert FLOW_J2.exists(), f"missing autologin flow blueprint: {FLOW_J2}"
    rendered = _env().from_string(FLOW_J2.read_text()).render({})
    doc = yaml.load(rendered, Loader=_FindLoader)
    assert isinstance(doc, dict) and "entries" in doc
    models = [e.get("model") for e in doc["entries"]]

    # The flow object with slug nos-autologin-flow.
    flows = [
        e
        for e in doc["entries"]
        if e.get("model") == "authentik_flows.flow"
        and e.get("identifiers", {}).get("slug") == AUTOLOGIN_FLOW
    ]
    assert flows, f"blueprint must declare a flow with slug {AUTOLOGIN_FLOW!r}"
    flow = flows[0]
    assert flow["attrs"]["designation"] == "authorization", (
        "nos-autologin-flow must be an authorization flow to be eligible as a "
        "provider authorization_flow"
    )

    # Dummy stage carrier — NO custom stage class.
    assert "authentik_stages_dummy.dummystage" in models, (
        "plan mandates a Dummy stage carrier (no custom stage class)"
    )

    # Per-flow branded background present (the splash surface), NOT inlined.
    bg = flow["attrs"].get("background")
    assert bg, "flow must carry a per-flow background (the branded splash surface)"
    assert not str(bg).startswith("data:"), (
        "background must be an asset PATH, not an inlined base64 image (image bloat)"
    )


def test_autologin_flow_is_implicit_consent_variant_no_consent_stage():
    """The plan's recommended-IF-VERIFIED variant carries NO consent stage
    (implicit consent). If silent-skip proves unreliable on the operator's
    Authentik version (GH #15814/#13068/#8660), they add a consent stage +
    expression policy — but the shipped default must be the consent-free flow."""
    doc = yaml.load(_env().from_string(FLOW_J2.read_text()).render({}), Loader=_FindLoader)
    models = [e.get("model") for e in doc["entries"]]
    consent = [m for m in models if str(m).startswith("authentik_stages_consent")]
    assert not consent, (
        "implicit-consent variant must NOT carry a consent stage; found "
        f"{consent}"
    )


def test_autologin_flow_documents_silent_skip_caveat():
    """HONESTY GATE: the blueprint must document that implicit-consent
    silent-skip is not guaranteed and must be verified end-to-end on the live
    Authentik version (operator step), citing the upstream regressions."""
    src = FLOW_J2.read_text()
    assert "#15814" in src and "#13068" in src and "#8660" in src, (
        "blueprint must cite the implicit-consent regressions GH "
        "#15814/#13068/#8660"
    )
    low = src.lower()
    assert "verify" in low and "operator" in low, (
        "blueprint must call out the operator end-to-end verification step"
    )


# ── 2. The 10-oidc-apps binding switch ─────────────────────────────────────


@pytest.mark.parametrize("enabled", [True, "True", "true", "yes"])
def test_binding_switches_when_autologin_enabled(enabled):
    slug = _authz_flow_slug(_render_oidc([_native_client(enabled)]), proxy=False)
    assert slug == AUTOLOGIN_FLOW, (
        f"autologin.enabled={enabled!r} must route authorization_flow to "
        f"{AUTOLOGIN_FLOW!r}, got {slug!r}"
    )


@pytest.mark.parametrize("enabled", [False, "False", "false", "no"])
def test_binding_unchanged_when_autologin_disabled(enabled):
    slug = _authz_flow_slug(_render_oidc([_native_client(enabled)]), proxy=False)
    assert slug == IMPLICIT_CONSENT, (
        f"autologin.enabled={enabled!r} must keep the implicit-consent default, "
        f"got {slug!r}"
    )


def test_binding_unchanged_for_client_without_autologin_block():
    """A client with no autologin block at all (today's universal shape) must
    render byte-identically — the implicit-consent default."""
    client = {
        "mode": "native_oidc",
        "client_id": "nos-x",
        "client_secret": "s",
        "slug": "x",
        "name": "X",
        "tier": 2,
        "enabled": True,
        "redirect_uris": ["https://x.dev.local/cb"],
        "launch_url": "https://x.dev.local",
    }
    slug = _authz_flow_slug(_render_oidc([client]), proxy=False)
    assert slug == IMPLICIT_CONSENT


def test_binding_unchanged_for_forward_auth_proxy_client():
    """forward_auth / proxy clients never carry an autologin block (pinned by
    test_no_autologin_for_pure_proxy_services); their proxyprovider
    authorization_flow stays the implicit-consent default."""
    client = {
        "mode": "forward_auth",
        "slug": "kiwix",
        "name": "Kiwix",
        "tier": 4,
        "enabled": True,
        "launch_url": "https://kiwix.dev.local",
    }
    slug = _authz_flow_slug(_render_oidc([client]), proxy=True)
    assert slug == IMPLICIT_CONSENT
