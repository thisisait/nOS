"""Every declared Authentik identity is proven able to log in, and a bad
synthetic persona can never block akadmin and the operator.

MEASURED 2026-10-18: `pazny` could not sign in with the derived nos_operator
password while identity-status said authentik=ok. 00-admin-groups sets that
password on every apply, but an import is all-or-nothing and the apply ran
`|| true` + `failed_when: false`; the synthetic-persona block lived in the
same file. Nothing read back that a declared identity can actually log in.

This renders the REAL templates (the plugin loader's render_dir, the loader's
Jinja env with lookup('vars')) and asserts: the personas live in their own
blueprint, the handlers apply it after 00 and do not swallow a failed 00, the
verify reads the blueprint instances' status, and `--tags verify` logs in
every nos_identities entry whose realms hold authentik.
"""
from __future__ import annotations

import json
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
SYNTHETIC = yaml.safe_load((REPO / "profiles/test-users.yml").read_text())["nos_synthetic_identities"]
PLUGIN = REPO / "files/anatomy/plugins/authentik-base"


class _Loader(yaml.SafeLoader):
    pass


_Loader.add_constructor("!Find", lambda ld, n: ("Find", ld.construct_sequence(n, deep=True)))


def _ctx(tmp: Path) -> dict:
    ctx = {"stacks_dir": str(tmp), "tenant_domain": "example.test", "nos_primary_admin": "op",
           "nos_operator_email": "op@example.test", "default_admin_email": "admin@example.test",
           "authentik_bootstrap_password": "pw-akadmin", "nos_operator_password": "pw-op",
           "nos_tester_password": "pw-tester", "authentik_bootstrap_token": "tok",
           "authentik_default_groups": CFG["authentik_default_groups"],
           "authentik_rbac_tiers": CFG["authentik_rbac_tiers"], ni.SYNTHETIC_FLAG: True}
    env = jinja2.Environment()
    rend = lambda i: {k: env.from_string(v).render(**ctx) if isinstance(v, str) else v for k, v in i.items()}  # noqa: E731
    ctx["nos_identities"] = [rend(i) for i in CFG["nos_identities"]]
    ctx["nos_synthetic_identities"] = [rend(i) for i in SYNTHETIC]
    for i in SYNTHETIC:
        ctx[i["password_var"]] = f"pw-{i['name']}"
    return ctx


def _users(path: Path) -> dict:
    doc = yaml.load(path.read_text(), _Loader)
    return {e["identifiers"]["username"]: e for e in doc["entries"] if e["model"] == "authentik_core.user"}


def test_a_bad_persona_cannot_block_the_operator(tmp_path):
    plugin = lp.Plugin.from_manifest_file(PLUGIN / "plugin.yml")
    note = lp._run_actions(plugin, "pre_compose", [{"render_dir": "provisioning.blueprints"}], _ctx(tmp_path))
    assert "rendered" in note, note
    out = tmp_path / "infra/authentik/blueprints"
    admin = _users(out / "00-admin-groups.yaml")
    assert {"akadmin", "op"} <= set(admin), "positive control: the SSO root and the operator left 00"
    leaked = sorted({i["name"] for i in SYNTHETIC} & set(admin))
    assert not leaked, f"personas {leaked} still share 00's all-or-nothing import with akadmin and the operator"
    personas = out / "05-synthetic-identities.yaml"
    assert personas.is_file(), "no 05-synthetic-identities blueprint — the personas have no home of their own"
    assert {i["name"] for i in SYNTHETIC} <= set(_users(personas)), "05 does not create the personas"


def test_the_apply_runs_05_after_00_and_a_failed_00_is_loud():
    main = next(h for h in yaml.safe_load((REPO / "main.yml").read_text())[0]["handlers"]
                if h["name"] == "Reapply authentik blueprints")
    role = next(h for h in yaml.safe_load((REPO / "roles/pazny.authentik/handlers/main.yml").read_text())
                if h["name"] == "Reapply authentik blueprints")
    for where, h in (("main.yml", main), ("roles/pazny.authentik", role)):
        loop = h["ansible.builtin.shell"]
        assert "00-admin-groups" in loop and "05-synthetic-identities" in loop, f"{where}: 05 is never applied"
        assert loop.index("00-admin-groups") < loop.index("05-synthetic-identities"), f"{where}: 05 before its groups"
        assert h.get("failed_when") is not False and "00-admin-groups" in str(h.get("failed_when")), (
            f"{where}: a failed 00-admin-groups apply is still swallowed")


def test_verify_reads_the_status_and_logs_every_identity_in(tmp_path):
    tasks = yaml.safe_load((REPO / "tasks/verify-authentik-apps.yml").read_text())
    assert any("/api/v3/managed/blueprints/" in str(t.get("ansible.builtin.uri", {}).get("url", "")) for t in tasks), (
        "nothing reads the blueprint instances' status — a failed import stays invisible")
    login = [t for t in tasks if "--login-only" in str(t.get("ansible.builtin.command", {}).get("argv", ""))]
    assert login, "no verify task logs a declared identity in through the flow executor"
    t = login[0]
    assert t.get("no_log") is True and "verify" in t["tags"], "the login check must be no_log and tagged verify"
    ctx = _ctx(tmp_path)
    ctx["lookup"] = lp.vars_lookup(ctx)
    sent = json.loads(lp._jinja_env().from_string(t["environment"]["NOS_FIRST_LOGIN"]).render(**ctx))
    want = {i["name"]: ctx[i["password_var"]] for i in ctx["nos_identities"] if "authentik" in i["realms"]}
    assert len(want) >= 3, "positive control: the defaults declare akadmin, the operator and the tester"
    assert {i["name"]: i["password"] for i in sent} == want, "a declared Authentik identity is not logged in"
