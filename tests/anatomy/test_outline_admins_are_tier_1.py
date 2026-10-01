"""Gate: Outline's admins are set to Authentik's tier-1 people, never to nobody.

2026-10-01: Outline makes its first sign-in admin — a tier-3 tester — and takes
no role from OIDC. tools/outline-roles.py reconciles users.role after the
first-login walk; these pin its SQL and its refusals without a database.
"""
import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("outline_roles", REPO / "tools/outline-roles.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def _run(monkeypatch, admins, present, dry=False):
    sent = []

    def psql(sql, container, db):
        sent.append(sql)
        if sql.startswith("SELECT"):
            return "\n".join(present)
        return ""
    monkeypatch.setattr(mod, "tier1_emails", lambda *a: set(admins))
    monkeypatch.setattr(mod, "psql", psql)
    monkeypatch.setenv("AUTHENTIK_TOKEN", "t")
    args = ["--authentik", "http://x", "--group", "nos-admins"] + (["--dry-run"] if dry else [])
    assert mod.main(args) == 0
    return sent


def test_admins_are_exactly_the_tier_1_people_present(monkeypatch):
    sql = _run(monkeypatch, {"a@x.eu", "gone@x.eu"}, ["a@x.eu", "tester@x.eu"])[-1]
    assert "role='admin' WHERE lower(email) IN ('a@x.eu')" in sql
    assert "role='member' WHERE role='admin' AND lower(email) NOT IN ('a@x.eu')" in sql
    assert sql.rstrip(";").endswith("COMMIT")


def test_no_tier_1_account_yet_changes_nothing(monkeypatch):
    sent = _run(monkeypatch, {"a@x.eu"}, ["tester@x.eu"])
    assert len(sent) == 1, "it demoted every admin with nobody to promote"


def test_dry_run_rolls_back(monkeypatch):
    assert _run(monkeypatch, {"a@x.eu"}, ["a@x.eu"], dry=True)[-1].rstrip(";").endswith("ROLLBACK")


def test_an_email_that_could_break_the_sql_is_never_admitted():
    assert not mod.EMAIL.match("x'@y.eu") and not mod.EMAIL.match("a@b.eu,c@d.eu")
