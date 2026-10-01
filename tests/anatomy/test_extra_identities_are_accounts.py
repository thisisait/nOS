"""The operator's own people (nos_extra_identities) are real accounts.

The profile builder's People step writes `nos_extra_identities: [{name, email,
tier}]` into config.yml — never a password. Pinned here, end to end offline:
main.yml refuses a malformed or colliding entry before anything renders, then
derives one password per name (nos_secret_map user_leaf, service nos-identity —
a dynamic name has no registry row); the REAL plugin-loader render of the
blueprint creates each person active in exactly their tier's group with that
password, and REFUSES to render a person without one; the first-login walk and
identity-status carry them; and the page's own output is the input.
"""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import jinja2
import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "files/anatomy/module_utils"))
import load_plugins as lp  # noqa: E402
import nos_secret_derive as derive  # noqa: E402

CFG = yaml.safe_load((REPO / "default.config.yml").read_text())
PLUGIN = REPO / "files/anatomy/plugins/authentik-base"
BP = "blueprints/00-admin-groups.yaml.j2"
PEOPLE = [{"name": "jana.novak", "email": "Jana@Example.test", "tier": 3},
          {"name": "petr", "email": "petr@example.test", "tier": 1}]


def _mod(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, REPO / path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _tier_group(tier: int) -> str:
    return next(t for t in CFG["authentik_rbac_tiers"] if t["tier"] == tier)["groups"][-1]


def _ctx(tmp: Path, people: list[dict], passwords: dict | None = None) -> dict:
    ctx = {"stacks_dir": str(tmp), "tenant_domain": "example.test", "nos_primary_admin": "op",
           "nos_operator_email": "op@example.test", "default_admin_email": "admin@example.test",
           "authentik_bootstrap_password": "pw-akadmin", "nos_operator_password": "pw-op",
           "nos_tester_password": "pw-tester", "authentik_bootstrap_token": "tok",
           "authentik_default_groups": CFG["authentik_default_groups"],
           "authentik_rbac_tiers": CFG["authentik_rbac_tiers"], "nos_test_users_enabled": False,
           "nos_extra_identities": people,
           "nos_extra_identity_passwords": {p["name"]: f"pw-{p['name']}" for p in people} if passwords is None else passwords}
    env = jinja2.Environment()
    ctx["nos_identities"] = [{k: env.from_string(v).render(**ctx) if isinstance(v, str) else v for k, v in i.items()}
                             for i in CFG["nos_identities"]]
    return ctx


class _Loader(yaml.SafeLoader):
    pass


_Loader.add_constructor("!Find", lambda ld, n: ("Find", ld.construct_sequence(n, deep=True)))


def _render_users(tmp: Path, people: list[dict], passwords: dict | None = None) -> dict:
    plugin = lp.Plugin.from_manifest_file(PLUGIN / "plugin.yml")
    lp._run_actions(plugin, "pre_compose", [{"render_dir": "provisioning.blueprints"}], _ctx(tmp, people, passwords))
    doc = yaml.load((tmp / "infra/authentik/blueprints/00-admin-groups.yaml").read_text(), _Loader)
    out: dict = {}
    for e in doc["entries"]:
        if e["model"] == "authentik_core.user":
            out.setdefault(e["identifiers"]["username"], []).append(e)
    return out


def test_the_roster_extension_is_declared_empty():
    assert CFG["nos_extra_identities"] == [], "the operator's list starts empty; config.yml fills it"


def test_each_person_is_active_in_their_tier_group_with_the_derived_password(tmp_path):
    users = _render_users(tmp_path, PEOPLE)
    assert "akadmin" in users and "op" in users, "positive control: the always-on accounts vanished"
    for p in PEOPLE:
        create, keep = users[p["name"]]
        # Set ONCE: the person owns the password after the first sign-in.
        assert create["state"] == "created" and create["attrs"]["password"] == f"pw-{p['name']}", p["name"]
        a = keep["attrs"]
        assert keep["state"] == "present" and "password" not in a, "a re-applied password undoes the person's own"
        assert a["is_active"] is True and a["email"] == p["email"].lower()
        assert a["groups"] == [("Find", ["authentik_core.group", ["name", _tier_group(p["tier"])]])], a["groups"]
        assert a["attributes"] == {"declared_by": "nos_extra_identities"}
    assert _tier_group(1) == "nos-admins" and _tier_group(3) == "nos-users", "tier → group meaning moved"
    role = (REPO / "roles/pazny.authentik/templates" / BP).read_text()
    assert role == (PLUGIN / BP).read_text(), "the role-side copy drifted from the rendered one"


def test_a_person_without_a_derived_password_is_refused_not_created_open(tmp_path):
    with pytest.raises(Exception, match="no derived password for petr"):
        _render_users(tmp_path, PEOPLE, passwords={"jana.novak": "pw"})
    assert "petr" not in _render_users(tmp_path / "none", []), "no people, no accounts"


def _task(name: str) -> dict:
    """A task from main.yml's play, by name — the source the playbook runs."""
    for play in yaml.safe_load((REPO / "main.yml").read_text()):
        for section in ("pre_tasks", "tasks", "post_tasks"):
            for t in play.get(section) or []:
                if t.get("name") == name:
                    return t
    raise AssertionError(f"main.yml has no task {name!r}")


def _holds(task: dict, ctx: dict) -> bool:
    env = lp._jinja_env()
    ctx = dict(ctx)
    for k, v in (task.get("vars") or {}).items():               # task vars are lists: render them as data
        ctx[k] = json.loads(env.from_string("{{ (" + v.strip()[2:-2] + ") | to_json }}").render(**ctx))
    return all(env.from_string("{{ (" + c + ") }}").render(**ctx) == "True" for c in task["ansible.builtin.assert"]["that"])


def _accepts(people: list[dict], tmp: Path) -> bool:
    ctx = _ctx(tmp, people)
    shape = _task("[Identities] Every extra person is well-formed")
    return all(_holds(shape, {**ctx, "item": p}) for p in people) and \
        _holds(_task("[Identities] No extra person collides with a declared account"), ctx)


@pytest.mark.parametrize("people,why", [
    ([{"name": "Jana", "email": "j@x.test", "tier": 3}], "uppercase name"),
    ([{"name": "jana-", "email": "j@x.test", "tier": 3}], "trailing dash"),
    ([{"name": "jana", "email": "nope", "tier": 3}], "no e-mail"),
    ([{"name": "jana", "email": "j@x.test", "tier": 5}], "no such tier"),
    ([{"name": "jan.a", "email": "a@x.test", "tier": 3}, {"name": "jan-a", "email": "b@x.test", "tier": 3}], "one secret subtree"),
    ([{"name": "alice", "email": "a2@x.test", "tier": 3}], "a declared account's name"),
    ([{"name": "op", "email": "o@x.test", "tier": 3}], "the operator's name"),
    ([{"name": "jana", "email": "ADMIN@example.test", "tier": 3}], "akadmin's e-mail"),
])
def test_main_yml_refuses_a_malformed_or_colliding_person(people, why, tmp_path):
    assert _accepts(PEOPLE, tmp_path), "positive control: a good list is refused"
    assert not _accepts(people, tmp_path), f"accepted: {why}"


def test_the_page_checks_names_with_the_playbooks_rule():
    shape = _task("[Identities] Every extra person is well-formed")["ansible.builtin.assert"]["that"][0]
    rule = re.search(r"regex_search\('(.+?)'\)", shape).group(1)
    tpl = (REPO / "tools/profile-builder/index.html.tpl").read_text()
    assert f"const NAME_RE = /{rule}/" in tpl, "the page would accept a name the playbook refuses, or the reverse"


def test_the_password_is_a_per_name_user_leaf_never_in_config():
    derive_task = _task("[Identities] Derive each extra person's password (user scope)")
    m = derive_task["nos_secret_map"]
    assert m["mode"] == "user_leaf" and m["service"] == "nos-identity" and m["purpose"] == "password"
    assert derive_task["no_log"] is True and "nos_extra_identities" in derive_task["loop"]
    fact = _task("[Identities] Expose the extra people's passwords")
    assert fact["no_log"] is True and "nos_extra_identity_passwords" in fact["ansible.builtin.set_fact"]
    master = bytes(range(32))
    leaves = {n: derive.user_leaf(master, derive.slugify_uid(n), "nos-identity", "password") for n in ("jana", "petr")}
    assert len(set(leaves.values())) == 2 and all(len(v) == 43 for v in leaves.values())
    assert leaves["jana"] != derive.user_leaf(master, "jana", "bsky", "password"), "the PDS leaf must not be the login"
    v1 = m["v1_suffix"].replace("{{ item.name }}", "jana")
    assert derive.v1_leaf("pfx", v1) == "pfx_pw_identity_jana"


def test_the_first_login_walk_carries_them_with_tier_and_password():
    task = yaml.safe_load((REPO / "tasks/first-login.yml").read_text())[0]
    ctx = _ctx(Path("/nonexistent"), PEOPLE)
    ctx["lookup"] = lp.vars_lookup(ctx)
    walked = {x["name"]: x for x in json.loads(lp._jinja_env().from_string(task["environment"]["NOS_FIRST_LOGIN"]).render(**ctx))}
    for p in PEOPLE:
        assert walked[p["name"]] == {"name": p["name"], "tier": p["tier"], "password": f"pw-{p['name']}",
                                     "own_password": True}
    assert "own_password" not in walked["akadmin"], "a system account's refused login stays a failure"
    assert "akadmin" in walked, "positive control: the declared roster is still walked"


def test_identity_status_declares_them(monkeypatch):
    ids = _mod("ids", "tools/identity-status.py")
    base = dict(CFG)
    monkeypatch.setattr(ids, "_yaml", lambda path: {"config.yml": {"nos_extra_identities": PEOPLE}}.get(path.name, base if path.name == "default.config.yml" else {}))
    roster, _ = ids.declared_roster()
    got = {r["name"]: r for r in roster}
    assert got["petr"]["realms"] == ["authentik"] and got["petr"]["kind"] == "user" and got["petr"]["tier"] == 1


@pytest.mark.skipif(not shutil.which("node"), reason="node runs the page's own renderConfig")
def test_what_the_page_writes_is_what_the_blueprint_renders(tmp_path):
    pb = _mod("pb", "tools/profile-builder-build.py")
    tpl = (REPO / "tools/profile-builder/index.html.tpl").read_text()
    logic = re.search(r'<script id="logic">(.*?)</script>', tpl, re.S).group(1)
    s = {"fields": {"global_password_prefix": "FAKEprefix12345678"}, "picks": {}, "mail": None, "manual": {},
         "people": [{"name": p["name"], "email": p["email"], "tier": str(p["tier"])} for p in PEOPLE]}
    out = subprocess.run(["node", "-e", logic + f"\nconst DATA={json.dumps(pb.build())};\nconst s={json.dumps(s)};\n"
                          "console.log(JSON.stringify({p: problems(DATA, s), y: renderConfig(DATA, s, mergeFlags(DATA, s.picks, s.mail, s.manual))}));"],
                         capture_output=True, text=True, check=True)
    res = json.loads(out.stdout)
    assert res["p"] == [], res["p"]
    people = yaml.safe_load(res["y"])["nos_extra_identities"]
    assert "password" not in res["y"].split("nos_extra_identities:", 1)[1].split("# services")[0].replace("nos-identity password", "")
    assert _accepts(people, tmp_path), "the playbook would refuse what the page wrote"
    users = _render_users(tmp_path, people)
    assert {p["name"] for p in PEOPLE} <= set(users)


def test_a_persons_own_password_is_not_a_failure_but_the_initial_one_is_named(monkeypatch, capsys):
    fl = _mod("fl", "tools/nos-first-login.py")
    monkeypatch.setattr(fl, "_plan", lambda: [])
    def login(name, *a, **k):
        if name in ("petr", "akadmin"):
            raise RuntimeError("refused")
        return object()
    monkeypatch.setattr(fl, "login", login)
    monkeypatch.setenv("NOS_FIRST_LOGIN", json.dumps([{"name": "petr", "password": "x", "own_password": True},
                                                      {"name": "jana", "password": "x", "own_password": True}]))
    assert fl.main(["--auth-host", "auth.x"]) == 0
    out = capsys.readouterr().out
    assert "petr: signs in with their own password" in out and "jana: still on the INITIAL password" in out
    monkeypatch.setenv("NOS_FIRST_LOGIN", json.dumps([{"name": "akadmin", "password": "x"}]))
    assert fl.main(["--auth-host", "auth.x"]) == 1
