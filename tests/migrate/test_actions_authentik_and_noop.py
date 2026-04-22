"""Authentik proxy + noop action tests."""

from __future__ import absolute_import, division, print_function

from module_utils.nos_migrate_actions import authentik_proxy, noop


def test_noop_returns_unchanged():
    res = noop.handle_noop({"reason": "irreversible"}, {})
    assert res["success"] is True
    assert res["changed"] is False
    assert res["result"]["reason"] == "irreversible"


def test_rename_group_prefix_delegates(base_ctx):
    ak = base_ctx["authentik_client"]
    ak.groups["devboxnos-admins"] = {"members": ["u1"], "policies": []}
    ak.groups["devboxnos-users"] = {"members": ["u2"], "policies": []}

    res = authentik_proxy.handle_rename_group_prefix(
        {"from_prefix": "devboxnos-", "to_prefix": "nos-"}, base_ctx)
    assert res["success"] is True
    assert res["changed"] is True
    assert "nos-admins" in ak.groups
    assert "nos-users" in ak.groups
    assert "devboxnos-admins" not in ak.groups


def test_rename_oidc_client_prefix_delegates(base_ctx):
    ak = base_ctx["authentik_client"]
    ak.oidc_clients["devboxnos-grafana"] = {}
    res = authentik_proxy.handle_rename_oidc_client_prefix(
        {"from_prefix": "devboxnos-", "to_prefix": "nos-"}, base_ctx)
    assert res["success"] is True
    assert "nos-grafana" in ak.oidc_clients


def test_authentik_missing_client_fails_clearly():
    ctx = {}  # no client injected, no factory, no import path
    res = authentik_proxy.handle_rename_group_prefix(
        {"from_prefix": "a", "to_prefix": "b"}, ctx)
    assert res["success"] is False
    assert "authentik" in res["error"].lower()
