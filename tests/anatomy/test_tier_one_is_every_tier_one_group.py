"""Tier 1 is every tier-1 group, never `groups | last`.

authentik_rbac_tiers[0].groups is ["nos-providers", "nos-admins"]; `| last`
keeps only nos-admins, so a provider was no GitLab admin, no tier-1 login in
the receptor map, no member of the unix realm (ssot/doctrine/permissions.md §4).
Each consumer is rendered with stock Jinja and must carry both groups.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import pathlib

import jinja2
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
TIERS = yaml.safe_load((REPO / "default.config.yml").read_text())["authentik_rbac_tiers"]
TIER1 = {"nos-providers", "nos-admins"}


def _env(undefined=jinja2.StrictUndefined):
    env = jinja2.Environment(undefined=undefined)
    env.filters["to_json"] = json.dumps
    env.filters["to_nice_json"] = lambda v: json.dumps(v, indent=4)
    env.filters["bool"] = bool
    env.filters["zip"] = lambda a, *b: list(zip(a, *b))  # ansible's zip
    return env


def test_the_genome_still_says_tier_one_is_two_groups():
    """Positive control: if tier 1 became one group, every check below is vacuous."""
    assert set(TIERS[0]["groups"]) == TIER1 and TIERS[0]["tier"] == 1, TIERS[0]


def test_gitlab_admin_groups_is_every_tier_one_group():
    tpl = (REPO / "roles/pazny.gitlab/templates/compose.yml.j2").read_text()
    out = _env(jinja2.ChainableUndefined).from_string(tpl).render(authentik_rbac_tiers=TIERS, install_authentik=True)
    line = next(ln for ln in out.splitlines() if "admin_groups:" in ln)
    held = set(line.split("admin_groups: [", 1)[1].split("]", 1)[0].replace("'", "").replace(" ", "").split(","))
    assert TIER1 <= held, f"GitLab admin_groups is {held}, tier 1 is {TIER1}"


def test_the_receptor_map_gives_a_tier_one_login_every_tier_one_group():
    tpl = (REPO / "roles/pazny.receptor/templates/identity-map.yml.j2").read_text()
    got = json.loads(_env().from_string(tpl).render(
        ansible_facts={"user_id": "op"}, nos_primary_admin="op", authentik_rbac_tiers=TIERS,
        nos_identities=[{"name": "op", "tier": 1}], nos_identity_map={},
        nos_extra_identities=[{"name": "u3", "tier": 3}]))["logins"]
    assert TIER1 <= set(got["op"]["groups"]), f"tier-1 login holds {got['op']['groups']}"
    assert got["u3"]["groups"] == ["nos-users"], "a tier-3 login must not gain tier-1 groups"


def test_the_unix_realm_puts_a_tier_one_login_in_every_tier_one_group():
    tasks = yaml.safe_load((REPO / "roles/pazny.linux.users/tasks/main.yml").read_text())
    expr = tasks[0]["ansible.builtin.set_fact"]["_unix_tier_group"]
    got = ast.literal_eval(_env().from_string(expr).render(authentik_rbac_tiers=TIERS).strip())
    own = {k: set(v) if isinstance(v, list) else {v} for k, v in got.items()}
    assert TIER1 <= own[1], f"a tier-1 host login joins {own[1]}"
    assert own[3] == {"nos-users"}, "a tier-3 login must not gain tier-1 groups"


def test_jupyterhub_counts_every_tier_one_group_as_the_unix_realm():
    tpl = (REPO / "roles/pazny.jupyterhub/templates/jupyterhub_config.py.j2").read_text()
    out = _env(jinja2.ChainableUndefined).from_string(tpl).render(authentik_rbac_tiers=TIERS)
    line = next(ln for ln in out.splitlines() if ln.startswith("UNIX_REALM_GROUPS ="))
    held = set(json.loads(line.split("=", 1)[1]))
    assert TIER1 <= held, f"UNIX_REALM_GROUPS is {held}"


def test_identity_status_reports_every_tier_one_group():
    spec = importlib.util.spec_from_file_location("identity_status", REPO / "tools/identity-status.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    tier_groups = getattr(mod, "tier_groups", None)
    assert tier_groups is not None, "identity-status names no tier's own groups (only groups[-1])"
    own = tier_groups({"authentik_rbac_tiers": TIERS})
    assert TIER1 <= set(own[1]), f"identity-status says tier 1 is {own[1]}"
    assert own[3] == ["nos-users"], own[3]
