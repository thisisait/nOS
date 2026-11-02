"""The end-of-run login hint says how to read a password, never the password.

THE SYMPTOM (2026-11-02, the Linux mini). A fresh host minted scheme v2 and replaced a
weak prefix, so the operator's `<prefix>_pw_authentik_admin` was wrong and nothing said
what was right; its mkcert CA had to be found and trusted by hand.

THE CHECK. Renders tasks/login-hint.yml's message for v1 and v2: v2 names the
nos-secret.py command, v1 the rule; neither carries a secret value, the prefix or the
master; the CA lines appear only for a local tenant with a readable CA.
"""
from __future__ import annotations

import jinja2
import yaml
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MSG = next(t for t in yaml.safe_load((REPO / "tasks/login-hint.yml").read_text())
           if t["name"].startswith("[Login] How to log in"))["ansible.builtin.debug"]["msg"]
SECRET = "fake-prefix-not-a-secret"


def _render(scheme: str, local: bool, ca_rc: int = 0) -> str:
    env = jinja2.Environment()
    env.filters["bool"] = lambda v: bool(v)
    return env.from_string(MSG).render(
        authentik_domain="auth.mini.local", nos_primary_admin="pazny", playbook_dir="/home/pazny/nOS",
        stacks_dir="/home/pazny/stacks", tenant_domain_is_local=local,
        _nos_secret_scheme={"scheme": scheme}, _login_ca={"rc": ca_rc, "stdout": "sha256 Fingerprint=3B:86"},
        global_password_prefix=SECRET, authentik_bootstrap_password=SECRET)


def test_v2_names_the_reader_command():
    out = _render("v2", True)
    assert "tools/nos-secret.py authentik_admin" in out and "akadmin" in out
    assert SECRET not in out


def test_v1_names_the_rule_not_the_value():
    out = _render("v1", True)
    assert "_pw_authentik_admin" in out and SECRET not in out


def test_the_ca_lines_only_for_a_local_tenant_with_a_ca():
    assert "rootCA.pem" in _render("v2", True) and "3B:86" in _render("v2", True)
    assert "rootCA.pem" not in _render("v2", False)
    assert "rootCA.pem" not in _render("v2", True, ca_rc=1)
