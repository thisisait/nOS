"""Anatomy gate: P0-MFA wiring (flags + reapply-loop + provider routing)."""
from __future__ import annotations

import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]


def test_flags_default_off_in_config():
    cfg = (REPO / "default.config.yml").read_text()
    assert "enforce_mfa: false" in cfg
    assert "mfa_password_hibp: false" in cfg
    assert "mfa_password_min_length: 15" in cfg


def test_gov_profile_opts_in():
    gov = (REPO / "profiles/gov-local.yml").read_text()
    assert "enforce_mfa: true" in gov


def test_reapply_handler_includes_mfa_blueprint():
    """RENDER the loop's inline Jinja, do not grep the whole file.

    plat-gate-shape (2026-09-04): `50-mfa-policy` lives only in the loop, but
    `enforce_mfa` also appears in a comment (main.yml:972) and an unrelated
    lockout guard (main.yml:2195) — so a bare `"enforce_mfa" in main` cannot
    tell the CONDITIONAL apply from a stray unconditional one. Making the apply
    unconditional (dropping the `if enforce_mfa` guard, keeping the token) is a
    real regression this must catch: the blueprint would apply on every normal
    run. Render the loop with the flag on AND off."""
    jinja2 = pytest.importorskip("jinja2")
    main = (REPO / "main.yml").read_text()
    loop = re.search(r"for bp in ([^\n;]*); do", main)
    assert loop, "main.yml: no 'for bp in …; do' reapply loop found"
    env = jinja2.Environment()
    env.filters["bool"] = bool  # ansible's `bool` filter, absent from plain jinja2
    on = env.from_string(loop.group(1)).render(enforce_mfa=True, authentik_engine="blueprint")
    off = env.from_string(loop.group(1)).render(enforce_mfa=False, authentik_engine="blueprint")
    assert "50-mfa-policy" in on, "the reapply loop must apply 50-mfa-policy when enforce_mfa is on"
    assert "50-mfa-policy" not in off, (
        "the reapply loop applies 50-mfa-policy even with enforce_mfa OFF — a "
        "stray apply on a normal run")


def test_oidc_blueprint_routes_tier1_only_when_flag_on():
    src = (REPO / "files/anatomy/plugins/authentik-base/blueprints/"
           "10-oidc-apps.yaml.j2").read_text()
    assert "nos-tier1-mfa-flow" in src
    assert "enforce_mfa" in src
    assert "authentication_flow" in src
    # the routing is gated on tier==1 so non-Tier-1 providers keep the stock flow
    assert "_tier | int == 1" in src
