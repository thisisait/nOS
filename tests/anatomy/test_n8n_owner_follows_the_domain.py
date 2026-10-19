"""The n8n owner follows a tenant_domain change instead of locking the converge.

n8n_admin_email derives from tenant_domain. On spark1 (2026-10-19) a domain
switch left the owner under the old email: the current login 401'd, owner
setup 400'd (owner exists), the previous-prefix leg could not name the owner,
and the converge failed. pazny.n8n post now reads the owner's email from n8n's
database READ-ONLY, logs in under it with the declared password, moves it via
the API, and a fresh login under the declared email is what the assert counts.
"""
from __future__ import annotations

import pathlib

import yaml

POST = pathlib.Path(__file__).resolve().parents[2] / "roles" / "pazny.n8n" / "tasks" / "post.yml"


def _tasks() -> list[dict]:
    return yaml.safe_load(POST.read_text())


def _named(part: str) -> dict:
    return next(t for t in _tasks() if part in t.get("name", ""))


def test_the_owner_is_read_without_writing_n8n_s_database():
    read = _named("Read the owner's email n8n holds")
    argv = read["ansible.builtin.command"]["argv"]
    assert "mode=ro" in " ".join(argv) and "UPDATE" not in " ".join(argv).upper()


def test_the_email_moves_through_the_api_and_a_reader_proves_it():
    move = _named("Move the owner to the declared email")["ansible.builtin.uri"]
    assert move["method"] == "PATCH" and move["url"].endswith("/rest/me")
    after = _named("Login under the declared email after the move")
    assert after["ansible.builtin.uri"]["url"].endswith("/rest/login")
    assert_task = _named("Owner credential must land")
    assert "_n8n_login_after_move.status" in str(assert_task["ansible.builtin.assert"]["that"])
    assert "_n8n_email_moved" not in str(assert_task["ansible.builtin.assert"]["that"]), \
        "the PATCH's own 200 is not proof — the later login is"
