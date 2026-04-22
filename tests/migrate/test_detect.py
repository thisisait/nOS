"""Predicate evaluator tests."""

from __future__ import absolute_import, division, print_function

import os

import pytest

from module_utils.nos_migrate_detect import evaluate, PredicateError


def test_fs_path_exists_shorthand(tmp_path, base_ctx):
    p = tmp_path / "exists"
    p.write_text("x")
    assert evaluate({"fs_path_exists": str(p)}, base_ctx) is True
    assert evaluate({"fs_path_exists": str(tmp_path / "nope")}, base_ctx) is False


def test_fs_path_exists_with_negate(tmp_path, base_ctx):
    p = tmp_path / "exists"
    p.write_text("x")
    assert evaluate({"fs_path_exists": str(p), "negate": True}, base_ctx) is False


def test_fs_path_exists_type_form(tmp_path, base_ctx):
    p = tmp_path / "exists"
    p.write_text("x")
    assert evaluate({"type": "fs_path_exists", "path": str(p)}, base_ctx) is True


def test_launchagent_matches(tmp_path, base_ctx):
    d = tmp_path / "LaunchAgents"
    d.mkdir()
    (d / "com.devboxnos.a.plist").write_text("")
    base_ctx["launchagents_dir"] = str(d)
    assert evaluate({"launchagent_matches": "com.devboxnos.*"}, base_ctx) is True
    assert evaluate({"launchagent_matches": "com.other.*"}, base_ctx) is False


def test_launchagents_matching_with_count(tmp_path, base_ctx):
    d = tmp_path / "LaunchAgents"
    d.mkdir()
    (d / "com.devboxnos.a.plist").write_text("")
    base_ctx["launchagents_dir"] = str(d)
    assert evaluate({"launchagents_matching": "com.devboxnos.*",
                     "count": 0}, base_ctx) is False
    # remove and recheck
    (d / "com.devboxnos.a.plist").unlink()
    assert evaluate({"launchagents_matching": "com.devboxnos.*",
                     "count": 0}, base_ctx) is True


def test_authentik_group_exists(base_ctx):
    base_ctx["authentik_client"].groups["nos-admins"] = {"members": []}
    assert evaluate({"authentik_group_exists": "nos-admins"}, base_ctx) is True
    assert evaluate({"authentik_group_exists": "nos-unicorns"}, base_ctx) is False


def test_state_schema_version_lt(base_ctx):
    base_ctx["state_client"].set("schema_version", 1)
    assert evaluate({"state_schema_version_lt": 2}, base_ctx) is True
    assert evaluate({"state_schema_version_lt": 1}, base_ctx) is False


def test_all_of_any_of_not(tmp_path, base_ctx):
    p = tmp_path / "here"
    p.write_text("")
    # all_of with one true, one false → false
    assert evaluate({"all_of": [
        {"fs_path_exists": str(p)},
        {"fs_path_exists": str(tmp_path / "ghost")},
    ]}, base_ctx) is False
    assert evaluate({"any_of": [
        {"fs_path_exists": str(p)},
        {"fs_path_exists": str(tmp_path / "ghost")},
    ]}, base_ctx) is True
    assert evaluate({"not": {"fs_path_exists": str(tmp_path / "ghost")}}, base_ctx) is True


def test_compose_image_tag_is(tmp_path, base_ctx):
    overrides = tmp_path / "stacks" / "observability" / "overrides"
    overrides.mkdir(parents=True)
    (overrides / "grafana.yml").write_text(
        "services:\n"
        "  grafana:\n"
        "    image: grafana/grafana-oss:11.5.0\n"
    )
    assert evaluate({"compose_image_tag_is": {
        "service": "grafana", "tag": "11.5.0",
        "overrides_dir": str(overrides),
    }}, base_ctx) is True
    assert evaluate({"compose_image_tag_is": {
        "service": "grafana", "tag": "12.0.0",
        "overrides_dir": str(overrides),
    }}, base_ctx) is False


def test_unknown_predicate_raises(base_ctx):
    with pytest.raises(PredicateError):
        evaluate({"wat": True}, base_ctx)
