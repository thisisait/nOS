"""An ephemeral E2E tester that fails half-way is deleted, not left behind.

2026-09-30: the Wing token mint failed on a stale wing.db path after the
Authentik user was created; 73 accounts piled up, two of them superusers.
provision_tester must roll the user back and re-raise.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tests/e2e"))

from lib import tester_identity as ti  # noqa: E402


class FakeAdmin:
    def __init__(self):
        self.users, self.calls = {}, []

    def get_group_by_name(self, name):
        return type("G", (), {"pk": "g1", "name": name})()

    def create_user(self, username, **_):
        self.users[username] = 7
        return type("U", (), {"pk": 7, "username": username})()

    def set_user_password(self, pk, pw):
        self.calls.append("password")

    def add_user_to_group(self, gpk, upk):
        self.calls.append("group+")

    def remove_user_from_group(self, gpk, upk):
        self.calls.append("group-")

    def delete_user(self, pk):
        self.calls.append("delete")
        self.users.clear()
        return True


def test_a_failed_token_mint_deletes_the_user(monkeypatch):
    def boom(name):
        raise RuntimeError("wing.db not found")
    monkeypatch.setattr(ti, "mint_token", boom)
    admin = FakeAdmin()
    with pytest.raises(RuntimeError):
        ti.provision_tester("provider", admin=admin)
    assert admin.users == {}, "the half-made tester was left in Authentik"
    assert admin.calls[-2:] == ["group-", "delete"], admin.calls


def test_the_default_wing_data_dir_is_the_deployed_one():
    src = (REPO / "tests/e2e/lib/wing_token_admin.py").read_text(encoding="utf-8")
    assert '"~/wing/app/data"' in src
