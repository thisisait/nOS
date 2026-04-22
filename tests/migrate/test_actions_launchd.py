"""Unit tests for launchd.* action handlers (uses a CmdRecorder to avoid
invoking real launchctl)."""

from __future__ import absolute_import, division, print_function

import os

import pytest

from module_utils.nos_migrate_actions import launchd as launchd_actions


def _make_agents(tmp_path, names):
    d = tmp_path / "LaunchAgents"
    d.mkdir()
    for name in names:
        (d / name).write_text("<plist>stub</plist>")
    return d


def test_bootout_happy(tmp_path, base_ctx):
    d = _make_agents(tmp_path, ["com.devboxnos.openclaw.plist",
                                "com.devboxnos.hermes.plist",
                                "eu.thisisait.nos.openclaw.plist"])
    base_ctx["launchagents_dir"] = str(d)
    res = launchd_actions.handle_bootout_and_delete(
        {"pattern": "com.devboxnos.*.plist", "directory": str(d)}, base_ctx)
    assert res["success"] is True
    assert res["changed"] is True
    # both old plists gone, new one preserved
    assert not (d / "com.devboxnos.openclaw.plist").exists()
    assert not (d / "com.devboxnos.hermes.plist").exists()
    assert (d / "eu.thisisait.nos.openclaw.plist").exists()
    # bootout was invoked for each
    bootout_calls = [c for c in base_ctx["run_cmd"].calls if c[:2] == ["launchctl", "bootout"]]
    assert len(bootout_calls) == 2


def test_bootout_no_matches_is_noop(tmp_path, base_ctx):
    d = _make_agents(tmp_path, ["eu.thisisait.nos.openclaw.plist"])
    res = launchd_actions.handle_bootout_and_delete(
        {"pattern": "com.devboxnos.*.plist", "directory": str(d)}, base_ctx)
    assert res["success"] is True
    assert res["changed"] is False


def test_bootout_missing_directory(tmp_path, base_ctx):
    missing = tmp_path / "nope"
    res = launchd_actions.handle_bootout_and_delete(
        {"pattern": "com.*.plist", "directory": str(missing)}, base_ctx)
    assert res["success"] is True
    assert res["changed"] is False


def test_kickstart_success(base_ctx, fake_proc):
    base_ctx["run_cmd"] = lambda cmd: fake_proc(0, "", "")
    res = launchd_actions.handle_kickstart(
        {"label": "eu.thisisait.nos.openclaw"}, base_ctx)
    assert res["success"] is True
    assert res["changed"] is True


def test_kickstart_unknown_label_is_soft_noop(base_ctx, fake_proc):
    base_ctx["run_cmd"] = lambda cmd: fake_proc(3, "", "Could not find service")
    res = launchd_actions.handle_kickstart(
        {"label": "eu.thisisait.nos.ghost"}, base_ctx)
    assert res["success"] is True
    assert res["changed"] is False


def test_kickstart_hard_error(base_ctx, fake_proc):
    base_ctx["run_cmd"] = lambda cmd: fake_proc(1, "", "Operation not permitted")
    res = launchd_actions.handle_kickstart(
        {"label": "eu.thisisait.nos.openclaw"}, base_ctx)
    assert res["success"] is False
