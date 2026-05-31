"""Anatomy gate: P0-MFA wiring (flags + reapply-loop + provider routing)."""
from __future__ import annotations

import pathlib

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
    main = (REPO / "main.yml").read_text()
    assert "50-mfa-policy" in main, "reapply handler must force-apply 50-mfa-policy"
    # only when the flag is on (guarded inline) — never a stray apply on a normal run
    assert "enforce_mfa" in main


def test_oidc_blueprint_routes_tier1_only_when_flag_on():
    src = (REPO / "files/anatomy/plugins/authentik-base/blueprints/"
           "10-oidc-apps.yaml.j2").read_text()
    assert "nos-tier1-mfa-flow" in src
    assert "enforce_mfa" in src
    assert "authentication_flow" in src
    # the routing is gated on tier==1 so non-Tier-1 providers keep the stock flow
    assert "_tier | int == 1" in src
