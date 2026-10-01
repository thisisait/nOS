"""Toggled identities (nos_identities `enabled_by`) are accounts only while on.

The RBAC test users (alice/bob/carol/dave, profiles/test-users.yml) live in
the one roster, gated by `nos_test_users_enabled`. Pinned here, against the
REAL plugin-loader render of the blueprint (the copy that reaches Authentik):
off renders none of them; on renders each active, in exactly the group its
tier adds in authentik_rbac_tiers, with the password its password_var names —
a registry leaf. The first-login walk and identity-status honour the same toggle.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import jinja2
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "files/anatomy/module_utils"))
import load_plugins as lp  # noqa: E402

CFG = yaml.safe_load((REPO / "default.config.yml").read_text())
CREDS_TEXT = (REPO / "default.credentials.yml").read_text()
REGISTRY = yaml.safe_load((REPO / "files/anatomy/secrets/registry.yml").read_text())["credentials"]
TOGGLED = [i for i in CFG["nos_identities"] if i.get("enabled_by")]
PLUGIN = REPO / "files/anatomy/plugins/authentik-base"


def _tier_group(tier: int) -> str:
    return next(t for t in CFG["authentik_rbac_tiers"] if t["tier"] == tier)["groups"][-1]


def _ctx(on: bool, tmp: Path) -> dict:
    """What nos_plugin_ctx carries for the vars the blueprint reads: rendered."""
    ctx = {"stacks_dir": str(tmp), "tenant_domain": "example.test", "nos_primary_admin": "op",
           "nos_operator_email": "op@example.test", "default_admin_email": "admin@example.test",
           "authentik_bootstrap_password": "pw-akadmin", "nos_operator_password": "pw-op",
           "nos_tester_password": "pw-tester", "authentik_bootstrap_token": "tok",
           "authentik_default_groups": CFG["authentik_default_groups"],
           "authentik_rbac_tiers": CFG["authentik_rbac_tiers"]}
    env = jinja2.Environment()
    ctx["nos_identities"] = [{k: env.from_string(v).render(**ctx) if isinstance(v, str) else v
                              for k, v in i.items()} for i in CFG["nos_identities"]]
    for i in TOGGLED:
        ctx[i["enabled_by"]] = on
        ctx[i["password_var"]] = f"pw-{i['name']}"
    return ctx


class _Loader(yaml.SafeLoader):
    pass


_Loader.add_constructor("!Find", lambda ld, n: ("Find", ld.construct_sequence(n, deep=True)))


def _render_users(on: bool, tmp: Path) -> dict:
    """Run the loader's own render_dir for authentik-base, read 00 back."""
    plugin = lp.Plugin.from_manifest_file(PLUGIN / "plugin.yml")
    note = lp._run_actions(plugin, "pre_compose", [{"render_dir": "provisioning.blueprints"}], _ctx(on, tmp))
    assert "rendered" in note, note
    doc = yaml.load((tmp / "infra/authentik/blueprints/00-admin-groups.yaml").read_text(), _Loader)
    return {e["identifiers"]["username"]: e for e in doc["entries"] if e["model"] == "authentik_core.user"}


def test_the_roster_declares_test_users_for_every_tier_below_admin():
    tiers = [i["tier"] for i in TOGGLED]
    assert {2, 3, 4} <= set(tiers), f"toggled identities cover tiers {sorted(set(tiers))}"
    assert any(tiers.count(t) >= 2 for t in tiers), "no tier holds two test users — isolation has no peer"
    emails = [i["email"] for i in CFG["nos_identities"]]
    assert len(emails) == len(set(emails)), "two identities share an email — apps keyed on email merge them"
    for i in TOGGLED:
        assert i["kind"] == "user" and i["realms"] == ["authentik"], i


def test_every_toggle_is_declared_and_off_by_default():
    for i in TOGGLED:
        assert CFG.get(i["enabled_by"]) is False, f"{i['name']}: {i['enabled_by']} must be declared false"


def test_every_password_var_resolves_to_a_registry_leaf():
    for i in TOGGLED:
        m = re.search(rf'^{i["password_var"]}:\s*"\{{\{{ nos_derived_secrets\.([a-z0-9_]+) \}}\}}"$',
                      CREDS_TEXT, re.M)
        assert m, f"{i['name']}: {i['password_var']} is not a nos_derived_secrets leaf in default.credentials.yml"
        assert m.group(1) in REGISTRY, f"{i['name']}: leaf {m.group(1)} has no registry row"


def test_off_the_blueprint_creates_none_of_them(tmp_path):
    users = _render_users(False, tmp_path)
    assert "akadmin" in users and "op" in users, "positive control: the always-on accounts vanished"
    leaked = sorted({i["name"] for i in TOGGLED} & set(users))
    assert not leaked, f"toggle off, yet the blueprint creates {leaked}"


def test_on_each_is_active_in_exactly_its_tier_group(tmp_path):
    users = _render_users(True, tmp_path)
    groups = {g["name"] for g in CFG["authentik_default_groups"]}
    assert _tier_group(2) == "nos-managers" and _tier_group(4) == "nos-guests", "tier → group meaning moved"
    for i in TOGGLED:
        u = users.get(i["name"])
        assert u, f"toggle on, yet the blueprint does not create {i['name']}"
        a = u["attrs"]
        assert a["is_active"] is True and a["password"] == f"pw-{i['name']}", i["name"]
        assert a["email"] == f"{i['name']}@example.test", a["email"]
        want = _tier_group(i["tier"])
        assert want in groups, want
        assert a["groups"] == [("Find", ["authentik_core.group", ["name", want]])], (i["name"], a["groups"])


def test_the_loader_lookup_reads_vars_and_nothing_else():
    look = lp.vars_lookup({"a": 1})
    assert look("vars", "a") == 1 and look("vars", "b", default=False) is False
    for bad in (lambda: look("vars", "b"), lambda: look("file", "a")):
        try:
            bad()
        except (KeyError, ValueError):
            continue
        raise AssertionError("lookup returned something it should refuse")


def _first_login_env(on: bool) -> list[dict]:
    task = yaml.safe_load((REPO / "tasks/first-login.yml").read_text())[0]
    ctx = _ctx(on, Path("/nonexistent"))
    ctx["lookup"] = lp.vars_lookup(ctx)
    return json.loads(lp._jinja_env().from_string(task["environment"]["NOS_FIRST_LOGIN"]).render(**ctx))


def test_the_first_login_walk_follows_the_toggle_and_carries_the_tier():
    off, on = _first_login_env(False), _first_login_env(True)
    names = {i["name"] for i in TOGGLED}
    assert not names & {x["name"] for x in off}, "first-login walks test users the blueprint never created"
    assert names <= {x["name"] for x in on}
    assert all("tier" in x for x in on), "the walker cannot skip apps above an identity's tier"
    spec = importlib.util.spec_from_file_location("fl", REPO / "tools/nos-first-login.py")
    fl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fl)
    assert fl.within_tier({"tier": 3}, {"tier": 3}) and fl.within_tier({"tier": 1}, {"tier": 4})
    assert not fl.within_tier({"tier": 4}, {"tier": 2}), "a guest would be walked into a manager app"


def test_identity_status_declares_them_only_while_on():
    spec = importlib.util.spec_from_file_location("ids", REPO / "tools/identity-status.py")
    ids = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ids)
    alice = next(i for i in TOGGLED if i["name"] == "alice")
    assert not ids.enabled(alice, {"nos_test_users_enabled": False}, {})
    assert ids.enabled(alice, {"nos_test_users_enabled": True}, {})
    assert ids.enabled(CFG["nos_identities"][0], {}, {}), "an ungated identity must always be declared"


def test_the_profile_turns_them_on():
    prof = yaml.safe_load((REPO / "profiles/test-users.yml").read_text())
    assert prof == {i["enabled_by"]: True for i in TOGGLED}, prof


def test_every_isolation_probe_renders_to_a_runnable_shape():
    """tests/e2e/estate/test_rbac_users.py runs these; a probe it cannot run
    would fail on the estate, not here."""
    spec = importlib.util.spec_from_file_location("e2e_plan", REPO / "tools/e2e-plan.py")
    plan = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(plan)
    rows = plan.plan({**plan.smoke.merge_config(REPO / "default.config.yml"), "tenant_domain": "example.test",
                      "_host_alias_seg": ""}, include_disabled=True)
    probes = [(r, p) for r in rows for p in r["isolation"]]
    assert len(probes) >= 2, "the isolation probes left the plugins"
    for r, p in probes:
        assert r["tier"] and r["first_login"], r["slug"]
        for step in ("write", "read"):
            assert "://" in p[step]["url"] and "{{" not in p[step]["url"], (r["slug"], step)
            # the leak check reads @secret@ (the content), never the object's name
            assert "@secret@" in json.dumps(p["write"]) and p[step]["status"], (r["slug"], step)
        assert p["peer"]["status"] and not set(p["peer"]["status"]) & set(p["read"]["status"]), (
            f"{r['slug']}: the peer may get the owner's status — only the body would tell them apart")
        used = re.findall(r"@(\w+)@", json.dumps(p))
        assert set(used) <= {"marker", "secret", "owner", "id"}, used
        assert ("owner" not in used or p.get("owner")) and ("id" not in used or p.get("id_path")), r["slug"]
