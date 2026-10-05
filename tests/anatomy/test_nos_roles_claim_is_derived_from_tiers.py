"""Gate: the nos_roles claim maps EVERY tier-1 group to admin, from the tiers.

2026-10-01: Gitea's --admin-group takes one name; tier 1 is two groups, so the
tier-1 tester (nos-providers) was no Gitea admin. One claim, one value per tier.
"""
import json
from pathlib import Path

import jinja2
import yaml

REPO = Path(__file__).resolve().parents[2]
CFG = yaml.safe_load((REPO / "default.config.yml").read_text())


def _expression(tiers) -> str:
    t = yaml.safe_load((REPO / "tasks/nos-roles.yml").read_text())[0]["ansible.builtin.set_fact"]["nos_roles_expression"]
    env = jinja2.Environment()
    env.filters["to_json"] = json.dumps
    return env.from_string(t).render(authentik_rbac_tiers=tiers)


def _roles_for(expr: str, groups: set) -> list:
    class G:
        def __init__(self, n): self.name = n
    class U:
        class ak_groups:
            @staticmethod
            def all(): return [G(g) for g in groups]
    class R:
        user = U
    body = "def f(request):\n" + "\n".join("    " + ln for ln in expr.splitlines())
    ns = {}
    exec(body, ns)  # noqa: S102 — the same Python Authentik runs, on a fake request
    return ns["f"](R)["nos_roles"]


def test_each_tier_1_group_is_admin_and_lower_tiers_are_not():
    expr = _expression(CFG["authentik_rbac_tiers"])
    tier1 = next(t for t in CFG["authentik_rbac_tiers"] if t["tier"] == 1)["groups"]
    for g in tier1:
        assert _roles_for(expr, {g}) == ["admin"], g
    assert _roles_for(expr, {"nos-users"}) == ["user"]
    assert _roles_for(expr, {"nos-guests"}) == ["guest"] and _roles_for(expr, set()) == []


def test_tofu_and_blueprint_both_attach_it():
    tf = (REPO / "terraform/authentik/services.tf").read_text()
    assert 'scope_name = "profile"' in tf and "nos_roles[*].id" in tf
    bp = (REPO / "files/anatomy/plugins/authentik-base/blueprints/10-oidc-apps.yaml.j2").read_text()
    assert bp.count('"nOS roles"') == 2
    assert '"nos_roles_expression": nos_roles_expression' in (REPO / "templates/tofu/nos.auto.tfvars.json.j2").read_text()


def test_nextcloud_provisions_groups_from_it_and_only_those():
    hook = yaml.safe_load((REPO / "files/anatomy/plugins/nextcloud-base/hooks/post_compose.yml").read_text())
    import shlex
    for sid in ("register_authentik_provider", "reconverge_provider_secret"):
        argv = shlex.split(next(s["cmd"] for s in hook["sequence"] if s["id"] == sid))
        assert "--group-provisioning=1" in argv and "--mapping-groups=nos_roles" in argv, sid
        assert "--group-whitelist-regex=^(admin|manager|user|guest)$" in argv, sid
