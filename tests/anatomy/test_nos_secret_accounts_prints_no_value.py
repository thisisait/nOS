"""Gate: `nos-secret.py --accounts` lists logins and key NAMES, never a value.

2026-10-02: the operator could not sign in to n8n — its login is config.yml's
n8n_admin_email, not admin@. --accounts answers "which login, which key"; the
value stays one explicit `nos-secret.py <key>` away.
"""
import ast
from pathlib import Path

SRC = (Path(__file__).resolve().parents[2] / "tools/nos-secret.py").read_text()


def test_accounts_never_derives_a_value():
    fn = next(n for n in ast.walk(ast.parse(SRC)) if isinstance(n, ast.FunctionDef) and n.name == "accounts")
    called = {getattr(c.func, "attr", getattr(c.func, "id", "")) for c in ast.walk(fn) if isinstance(c, ast.Call)}
    assert not called & {"estate_leaf", "user_leaf", "master_bytes", "_store"}, called


def test_the_verb_is_wired():
    assert 'argv == ["--accounts"]' in SRC
