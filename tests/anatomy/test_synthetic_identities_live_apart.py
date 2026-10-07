"""Synthetic identities live apart from people, and retire instead of lingering.

alice/bob/carol/dave are `kind: synthetic` in profiles/test-users.yml
(`nos_synthetic_identities`), never in default.config.yml `nos_identities`,
which holds real accounts only. One switch, `nos_test_users_enabled`:
on, the REAL plugin-loader render of the blueprint creates each one active in
exactly its tier's group, tagged synthetic; off, an unconfirmed run renders
none (they linger, the run says so) and only `-e retire_synthetic=true`
renders `state: absent`, identified by username AND attributes.kind synthetic,
so a person who merely shares the name is never matched (Authentik ANDs the
identifiers, a dict value is `__contains`). `nos -y` / `--confirm` retire nothing. Every reader that
lists accounts labels a synthetic one as synthetic, never as a person.
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
sys.path.insert(0, str(REPO / "tools"))
import load_plugins as lp  # noqa: E402
import nos_identity as ni  # noqa: E402

CFG = ni.default_config()
CREDS_TEXT = (REPO / "default.credentials.yml").read_text()
REGISTRY = yaml.safe_load((REPO / "files/anatomy/secrets/registry.yml").read_text())["credentials"]
PROFILE = yaml.safe_load((REPO / "profiles/test-users.yml").read_text())
SYNTHETIC = PROFILE.get("nos_synthetic_identities") or []
PLUGIN = REPO / "files/anatomy/plugins/authentik-base"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _tier_group(tier: int) -> str:
    return next(t for t in CFG["authentik_rbac_tiers"] if t["tier"] == tier)["groups"][-1]


def _ctx(on: bool, tmp: Path, confirmed: bool = False, retire: bool = False) -> dict:
    """What nos_plugin_ctx carries for the vars the blueprint reads: rendered."""
    ctx = {"stacks_dir": str(tmp), "tenant_domain": "example.test", "nos_primary_admin": "op",
           "nos_operator_email": "op@example.test", "default_admin_email": "admin@example.test",
           "authentik_bootstrap_password": "pw-akadmin", "nos_operator_password": "pw-op",
           "nos_tester_password": "pw-tester", "authentik_bootstrap_token": "tok",
           "authentik_default_groups": CFG["authentik_default_groups"],
           "authentik_rbac_tiers": CFG["authentik_rbac_tiers"],
           ni.SYNTHETIC_FLAG: on, "nos_confirmed": confirmed}
    if retire:
        ctx["retire_synthetic"] = "true"   # as -e passes it
    env = jinja2.Environment()
    rend = lambda i: {k: env.from_string(v).render(**ctx) if isinstance(v, str) else v for k, v in i.items()}  # noqa: E731
    ctx["nos_identities"] = [rend(i) for i in CFG["nos_identities"]]
    ctx["nos_synthetic_identities"] = [rend(i) for i in SYNTHETIC]   # what main.yml adopts from the profile
    for i in SYNTHETIC:
        ctx[i["password_var"]] = f"pw-{i['name']}"
    return ctx


class _Loader(yaml.SafeLoader):
    pass


_Loader.add_constructor("!Find", lambda ld, n: ("Find", ld.construct_sequence(n, deep=True)))


def _render_users(on: bool, tmp: Path, confirmed: bool = False, retire: bool = False) -> dict:
    """Run the loader's own render_dir for authentik-base, read 00 back."""
    plugin = lp.Plugin.from_manifest_file(PLUGIN / "plugin.yml")
    note = lp._run_actions(plugin, "pre_compose", [{"render_dir": "provisioning.blueprints"}], _ctx(on, tmp, confirmed, retire))
    assert "rendered" in note, note
    doc = yaml.load((tmp / "infra/authentik/blueprints/00-admin-groups.yaml").read_text(), _Loader)
    return {e["identifiers"]["username"]: e for e in doc["entries"] if e["model"] == "authentik_core.user"}


def test_the_defaults_declare_no_synthetic_identity():
    for i in CFG["nos_identities"]:
        assert i.get("kind") != "synthetic" and "enabled_by" not in i, f"{i['name']} is synthetic, yet in the defaults"
    assert CFG.get("nos_synthetic_identities") == [], "the defaults hold a synthetic roster — the profile owns it"
    assert CFG.get(ni.SYNTHETIC_FLAG) is False, f"{ni.SYNTHETIC_FLAG} must be declared false"


def test_the_profile_declares_them_synthetic_for_every_tier_below_admin():
    assert PROFILE[ni.SYNTHETIC_FLAG] is True, "the profile no longer switches them on"
    tiers = [i["tier"] for i in SYNTHETIC]
    assert {2, 3, 4} <= set(tiers), f"synthetic identities cover tiers {sorted(set(tiers))}"
    assert any(tiers.count(t) >= 2 for t in tiers), "no tier holds two test users — isolation has no peer"
    emails = [i["email"] for i in CFG["nos_identities"] + SYNTHETIC]
    assert len(emails) == len(set(emails)), "two identities share an email — apps keyed on email merge them"
    for i in SYNTHETIC:
        assert i["kind"] == "synthetic" and i["realms"] == ["authentik"], i
    assert [i["name"] for i in ni.synthetic_identities({})] == [i["name"] for i in SYNTHETIC]
    assert ni.synthetic_identities({"nos_synthetic_identities": [{"name": "zed"}]}) == [{"name": "zed", "kind": "synthetic"}]


def test_every_password_var_resolves_to_a_registry_leaf():
    for i in SYNTHETIC:
        m = re.search(rf'^{i["password_var"]}:\s*"\{{\{{ nos_derived_secrets\.([a-z0-9_]+) \}}\}}"$',
                      CREDS_TEXT, re.M)
        assert m, f"{i['name']}: {i['password_var']} is not a nos_derived_secrets leaf in default.credentials.yml"
        assert m.group(1) in REGISTRY, f"{i['name']}: leaf {m.group(1)} has no registry row"


def test_off_and_unconfirmed_the_blueprint_leaves_them_alone(tmp_path):
    users = _render_users(False, tmp_path)
    assert "akadmin" in users and "op" in users, "positive control: the always-on accounts vanished"
    leaked = sorted({i["name"] for i in SYNTHETIC} & set(users))
    assert not leaked, f"toggle off, yet the blueprint touches {leaked}"


def test_off_and_confirmed_alone_retires_nobody(tmp_path):
    """`nos -y` emits confirm=true on every unattended converge — not consent."""
    users = _render_users(False, tmp_path, confirmed=True)
    leaked = sorted({i["name"] for i in SYNTHETIC} & set(users))
    assert not leaked, f"confirm=true (any -y run) retires {leaked} without -e retire_synthetic=true"


def test_off_and_retire_removes_only_accounts_tagged_synthetic(tmp_path):
    users = _render_users(False, tmp_path, retire=True)
    assert users["akadmin"]["state"] == "present", "positive control: a retire run retired the SSO root"
    for i in SYNTHETIC:
        u = users.get(i["name"])
        assert u and u["state"] == "absent", f"toggle off + retire_synthetic, yet {i['name']} is not retired: {u}"
        assert u["identifiers"] == {"username": i["name"], "attributes": {"kind": "synthetic"}}, (
            f"{i['name']}: retire matches on more than the synthetic tag — a person named so would be deleted")
        assert "password" not in (u.get("attrs") or {}), i["name"]


def test_on_retire_is_ignored(tmp_path):
    users = _render_users(True, tmp_path, retire=True)
    assert all(users[i["name"]]["state"] == "present" for i in SYNTHETIC)


def test_on_each_is_active_in_exactly_its_tier_group_and_tagged_synthetic(tmp_path):
    users = _render_users(True, tmp_path)
    groups = {g["name"] for g in CFG["authentik_default_groups"]}
    assert _tier_group(2) == "nos-managers" and _tier_group(4) == "nos-guests", "tier → group meaning moved"
    for i in SYNTHETIC:
        u = users.get(i["name"])
        assert u and u["state"] == "present", f"toggle on, yet the blueprint does not create {i['name']}"
        a = u["attrs"]
        assert a["is_active"] is True and a["password"] == f"pw-{i['name']}", i["name"]
        assert a["email"] == f"{i['name']}@example.test", a["email"]
        assert a["attributes"] == {"kind": "synthetic"}, "Authentik cannot tell a synthetic account from a person"
        want = _tier_group(i["tier"])
        assert want in groups, want
        assert a["groups"] == [("Find", ["authentik_core.group", ["name", want]])], (i["name"], a["groups"])


def _first_login_env(on: bool) -> list[dict]:
    task = yaml.safe_load((REPO / "tasks/first-login.yml").read_text())[0]
    ctx = _ctx(on, Path("/nonexistent"))
    ctx["lookup"] = lp.vars_lookup(ctx)
    return json.loads(lp._jinja_env().from_string(task["environment"]["NOS_FIRST_LOGIN"]).render(**ctx))


def test_the_first_login_walk_follows_the_toggle_and_carries_the_tier():
    off, on = _first_login_env(False), _first_login_env(True)
    names = {i["name"] for i in SYNTHETIC}
    assert not names & {x["name"] for x in off}, "first-login walks test users the blueprint never created"
    assert names <= {x["name"] for x in on}
    assert all("tier" in x for x in on), "the walker cannot skip apps above an identity's tier"
    fl = _load("nos-first-login")
    assert fl.within_tier({"tier": 3}, {"tier": 3}) and fl.within_tier({"tier": 1}, {"tier": 4})
    assert not fl.within_tier({"tier": 4}, {"tier": 2}), "a guest would be walked into a manager app"


def test_main_adopts_the_profile_roster_and_the_dry_run_names_them():
    """config.yml with only `nos_test_users_enabled: true` keeps the personas:
    main.yml reads the profile's roster (namespaced, so the flag stays the
    operator's) and adopts it when nothing declared one."""
    main = yaml.safe_load((REPO / "main.yml").read_text())[0]
    pre = main["pre_tasks"]
    inc = next((t for t in pre if (t.get("ansible.builtin.include_vars") or {}).get("file") == "profiles/test-users.yml"), None)
    assert inc and inc["ansible.builtin.include_vars"].get("name"), "the profile is included flat — its flag would force the users on"
    adopt = next((t for t in pre if "nos_synthetic_identities" in (t.get("ansible.builtin.set_fact") or {})), None)
    assert adopt and "nos_synthetic_identities" in adopt["when"] and "always" in adopt["tags"], adopt
    assert pre.index(inc) < pre.index(adopt)
    text = (REPO / "main.yml").read_text()
    assert "nos_synthetic_identities" in text.split("_taken:", 1)[1].split("\n", 1)[0], "a person may take a synthetic name"
    dry = [t for t in main["tasks"] if "retire_synthetic=true" in str(t.get("ansible.builtin.debug", ""))]
    assert dry and "retire_synthetic" in dry[0]["when"] and ni.SYNTHETIC_FLAG in dry[0]["when"], "no dry-run notice before a retire"
    assert "nos_confirmed" not in str(dry[0]), "the notice still promises a -y/--confirm retire"


def test_identity_status_labels_them_synthetic_and_names_the_lingering():
    ids = _load("identity-status")
    base = {"nos_identities": CFG["nos_identities"], "authentik_rbac_tiers": CFG["authentik_rbac_tiers"]}
    on, _ = ids.declared_roster({**base, ni.SYNTHETIC_FLAG: True})
    off, _ = ids.declared_roster({**base, ni.SYNTHETIC_FLAG: False})
    names = {i["name"] for i in SYNTHETIC}
    assert {i["name"]: i["kind"] for i in on if i["name"] in names} == {n: "synthetic" for n in names}
    assert not names & {i["name"] for i in off}
    assert {i["name"] for i in off} <= {i["name"] for i in on}, "the people changed with the toggle"
    assert "synthetic" in ids.lingering({**base, ni.SYNTHETIC_FLAG: False}, ["alice", "someone"])
    assert ids.lingering({**base, ni.SYNTHETIC_FLAG: True}, ["alice"]) == ""
    assert ids.lingering({**base, ni.SYNTHETIC_FLAG: False}, ["someone"]) == ""


def test_e2e_plan_resolves_them_synthetic_only_while_on():
    plan = _load("e2e-plan")
    base = {**plan.smoke.merge_config(*ni.default_layers()), "tenant_domain": "example.test", "_host_alias_seg": ""}
    on = plan.identities({**base, ni.SYNTHETIC_FLAG: True})
    off = plan.identities({**base, ni.SYNTHETIC_FLAG: False})
    assert {i["name"]: i["kind"] for i in on if i["name"] == "alice"} == {"alice": "synthetic"}
    assert all(i["kind"] != "synthetic" for i in off) and len(off) == len(CFG["nos_identities"])
    rbac = (REPO / "tests/e2e/estate/test_rbac_users.py").read_text()
    assert 'kind") == "synthetic"' in rbac and "enabled_by" not in rbac, "the RBAC journey still keys on enabled_by"


def test_the_profile_builder_reads_the_roster_and_writes_only_the_switch():
    pb = _load("profile-builder-build")
    acc = pb.accounts()
    assert [u["name"] for u in acc["test_users"]] == [i["name"] for i in SYNTHETIC]
    assert set(i["name"] for i in SYNTHETIC) <= set(acc["reserved"]), "a person may take a synthetic name"
    prof = next(p for p in pb.profiles() if p["id"] == "test-users")
    assert prof["knobs"] == {ni.SYNTHETIC_FLAG: True} and prof["step"] == "accounts", prof


def test_every_isolation_probe_renders_to_a_runnable_shape():
    """tests/e2e/estate/test_rbac_users.py runs these; a probe it cannot run
    would fail on the estate, not here."""
    plan = _load("e2e-plan")
    rows = plan.plan({**plan.smoke.merge_config(*ni.default_layers()), "tenant_domain": "example.test",
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
