"""state.set / state.bump_schema_version tests."""

from __future__ import absolute_import, division, print_function

import pytest

from module_utils.nos_migrate_actions import state_ops


def test_state_set_happy(base_ctx):
    res = state_ops.handle_state_set(
        {"path": "identifiers.launchd_prefix", "value": "eu.thisisait.nos"},
        base_ctx)
    assert res["success"] is True
    assert res["changed"] is True
    assert base_ctx["state_client"].get("identifiers.launchd_prefix") == "eu.thisisait.nos"


def test_state_set_idempotent(base_ctx):
    base_ctx["state_client"].set("a.b", "v")
    res = state_ops.handle_state_set({"path": "a.b", "value": "v"}, base_ctx)
    assert res["success"] is True
    assert res["changed"] is False


def test_state_set_requires_value(base_ctx):
    res = state_ops.handle_state_set({"path": "a.b"}, base_ctx)
    assert res["success"] is False


def test_bump_schema_version_forward(base_ctx):
    base_ctx["state_client"].set("schema_version", 1)
    res = state_ops.handle_bump_schema_version({"to": 2}, base_ctx)
    assert res["success"] is True
    assert res["changed"] is True
    assert base_ctx["state_client"].get("schema_version") == 2


def test_bump_schema_version_noop_when_at_or_above(base_ctx):
    base_ctx["state_client"].set("schema_version", 5)
    res = state_ops.handle_bump_schema_version({"to": 2}, base_ctx)
    assert res["success"] is True
    assert res["changed"] is False
    assert base_ctx["state_client"].get("schema_version") == 5
