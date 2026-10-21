"""Anatomy gate — a manifest app states its RBAC tier once, or twice the same.

THE SYMPTOM (2026-10-21, RBAC inventory). apps/twofauth.yml said
``authentik.tier: 3`` beside ``nginx.rbac_tier: 1`` ("TOTP secrets are operator
credentials, only admins should reach this UI"). load_plugins resolves
authentik.tier first, so every user-tier person reached the TOTP vault.

THE CHECK. In every apps/*.yml (and *.yml.draft), when both fields are present
they are equal. The permission genome (ssot/doctrine/permissions.md) removes the
second spelling; until then two spellings must say one thing.
"""

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]


def test_the_two_tier_fields_agree():
    bad = []
    for p in sorted([*(REPO / "apps").glob("*.yml"), *(REPO / "apps").glob("*.yml.draft")]):
        app = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        a = (app.get("authentik") or {}).get("tier")
        n = (app.get("nginx") or {}).get("rbac_tier")
        if a is not None and n is not None and a != n:
            bad.append(f"{p.name}: authentik.tier {a} != nginx.rbac_tier {n} (authentik.tier wins)")
    assert not bad, bad
