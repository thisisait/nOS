"""BookStack drops the Admin role when a person leaves nos-admins (SSO, ssot/doctrine/gates.md §7).

Ruling 2026-11-11 (row sso-admin-claims-long-tail): the declared roster wins. With
OIDC_USER_TO_GROUPS alone BookStack only ever ADDS roles, so a demoted person kept admin for
ever; the 2026-11-11 review found the batch shipped that. The rendered env must carry both.
"""
from __future__ import annotations

from pathlib import Path

import jinja2

REPO = Path(__file__).resolve().parents[2]


def _render() -> dict[str, str]:
    env = jinja2.Environment(undefined=jinja2.ChainableUndefined)
    env.filters.update({"bool": lambda v: bool(v), "to_json": str})
    text = env.from_string((REPO / "roles/pazny.bookstack/templates/env.j2").read_text()).render(
        install_authentik=True, bookstack_oidc_enabled=True, nos_derived_secrets={"oidc_bookstack": "FAKE_x"})
    return dict(line.split("=", 1) for line in text.splitlines() if "=" in line and not line.startswith("#"))


def test_group_sync_both_adds_and_removes():
    env = _render()
    if env.get("OIDC_USER_TO_GROUPS") == "true":
        assert env.get("OIDC_REMOVE_FROM_GROUPS") == "true", (
            "BookStack maps OIDC groups to roles but never removes them: a person who leaves "
            "nos-admins keeps Admin (ruling 2026-11-11, sso-admin-claims-long-tail)")
    else:
        raise AssertionError(f"the OIDC block did not render (env keys: {sorted(env)[:8]})")
