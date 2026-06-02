"""Anatomy gate (P0-3) — default-brand authentication-flow routing.

46-brand-auth-flow.yaml.j2 ALWAYS emits exactly one brand entry (identifier
domain 'authentik-default') so the brand's flow_authentication is explicitly
(re)set in BOTH flag states — Authentik state:present is a partial update with no
cascade-delete, so an omitted entry would strand the brand on a prior run's flow.

  enforce_mfa ON  → flow_authentication routes direct logins through nos-tier1-mfa-flow
  enforce_mfa OFF → resets to the stock default-authentication-flow

CI-safe: renders via the loader jinja env; no Docker / Authentik.
"""
from __future__ import annotations

import pathlib
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
BRAND_J2 = REPO / "files/anatomy/plugins/authentik-base/blueprints/46-brand-auth-flow.yaml.j2"
sys.path.insert(0, str(REPO / "files/anatomy/module_utils"))


class _FindLoader(yaml.SafeLoader):
    pass


_FindLoader.add_constructor(
    "!Find", lambda loader, node: {"__Find__": loader.construct_sequence(node, deep=True)}
)


def _render(enforce: bool) -> str:
    import load_plugins  # noqa: WPS433

    return load_plugins._jinja_env().from_string(BRAND_J2.read_text()).render(enforce_mfa=enforce)


def _brand(enforce: bool) -> dict:
    doc = yaml.load(_render(enforce), Loader=_FindLoader)
    brands = [e for e in (doc.get("entries") or []) if e.get("model") == "authentik_brands.brand"]
    assert len(brands) == 1, f"expected exactly one brand entry (enforce_mfa={enforce}), got {len(brands)}"
    assert brands[0]["identifiers"]["domain"] == "authentik-default"
    return brands[0]


def _flow_slug(brand: dict) -> str:
    return brand["attrs"]["flow_authentication"]["__Find__"][1][1]


def test_always_emits_brand_both_flag_states():
    for flag in (True, False):
        out = _render(flag)
        assert "authentik_brands.brand" in out, f"brand must emit with enforce_mfa={flag}"
        assert "{{" not in out and "{%" not in out, f"unrendered jinja with enforce_mfa={flag}"


def test_on_routes_through_mfa_flow():
    assert _flow_slug(_brand(True)) == "nos-tier1-mfa-flow"


def test_off_resets_to_stock_flow():
    assert _flow_slug(_brand(False)) == "default-authentication-flow"
