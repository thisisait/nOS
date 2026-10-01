"""Gate: every declared identity has its account in every SSO app from install.

Operator ask 2026-10-01: nOS admin, nOS tester and the operator (admin rights)
exist — and are active — from the first install, not from a first visit.
Authentik gets them from the 00-admin-groups blueprint; each app gets them from
tools/nos-first-login.py walking the plugin's authentik.first_login.
"""
import importlib.util
import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
CFG = yaml.safe_load((REPO / "default.config.yml").read_text())
CREDS = yaml.safe_load((REPO / "default.credentials.yml").read_text())
# Always-on identities; toggled ones (enabled_by) are pinned by
# test_toggled_identities_are_gated_accounts.py.
IDS = [i for i in CFG["nos_identities"] if "authentik" in i.get("realms", []) and not i.get("enabled_by")]
spec = importlib.util.spec_from_file_location("first_login", REPO / "tools/nos-first-login.py")
fl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fl)


def test_the_three_are_declared_with_a_password():
    names = [i["name"] for i in IDS]
    assert names[0] == "akadmin" and "{{ nos_primary_admin }}" in names and len(names) == 3, names
    for i in IDS:
        assert i.get("password_var") in {**CFG, **CREDS}, i


def test_authentik_creates_each_one_active():
    bp = (REPO / "files/anatomy/plugins/authentik-base/blueprints/00-admin-groups.yaml.j2").read_text()  # renders
    users = re.findall(r"model: authentik_core\.user\n.*?username: (.+?)\n.*?is_active: (\w+)", bp, re.S)
    made = {u.strip().strip('"'): active for u, active in users}
    for i in IDS:
        assert made.get(i["name"]) == "true", (i["name"], made)


def test_every_sso_plugin_says_how_accounts_are_made():
    for f in sorted((REPO / "files/anatomy/plugins").glob("*/plugin.yml")):
        ak = (yaml.safe_load(f.read_text()) or {}).get("authentik") or {}
        if ak.get("mode") == "native_oidc":
            assert bool(ak.get("first_login")) != bool(ak.get("first_login_blocked")), f.parent.name


def test_a_login_page_is_not_a_landing():
    page = '<a class="alogin" href="https://auth.x/application/o/authorize/?client_id=c&amp;state=s">'
    w = fl.walk.__globals__["Walk"](fl.REACHED, "https://app.x/", 200, [])
    assert not fl.landed(w, "https://app.x/", page, "auth.x")
    assert fl.sso_button(page, "auth.x", "https://app.x/")[1].endswith("client_id=c&state=s")
    assert fl.landed(w, "https://app.x/", "<h1>home</h1>", "auth.x")


def test_a_logout_form_is_not_a_login_button():
    logout = '<form action="https://app.x/oidc/logout" method="POST"><input type="hidden" name="_token" value="t">'
    login = logout.replace("logout", "login")
    assert fl.sso_button(logout, "auth.x", "https://app.x/") is None
    assert fl.sso_button(login, "auth.x", "https://app.x/") == ("POST", "https://app.x/oidc/login", {"_token": "t"})


def test_the_run_walks_them_and_never_prints_a_password():
    main = (REPO / "main.yml").read_text()
    post = main[main.index("  post_tasks:"):]
    assert post.index("tasks/post-smoke.yml") < post.index("tasks/first-login.yml")  # smoke always reports
    walk = yaml.safe_load((REPO / "tasks/first-login.yml").read_text())[0]
    assert walk["no_log"] is True and "password_var" in walk["environment"]["NOS_FIRST_LOGIN"]
