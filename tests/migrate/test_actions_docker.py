"""docker.compose_override_rename + docker.volume_clone tests."""

from __future__ import absolute_import, division, print_function

import pytest

from module_utils.nos_migrate_actions import docker_compose


def test_compose_override_rename_happy(tmp_path, base_ctx):
    stacks = tmp_path / "stacks"
    overrides = stacks / "infra" / "overrides"
    overrides.mkdir(parents=True)
    (overrides / "openclaw.yml").write_text("services: {}\n")

    res = docker_compose.handle_compose_override_rename({
        "stack": "infra",
        "from_name": "openclaw",
        "to_name": "opencode",
        "stacks_dir": str(stacks),
    }, base_ctx)
    assert res["success"] is True
    assert res["changed"] is True
    assert (overrides / "opencode.yml").is_file()
    assert not (overrides / "openclaw.yml").exists()


def test_compose_override_rename_idempotent(tmp_path, base_ctx):
    stacks = tmp_path / "stacks"
    overrides = stacks / "infra" / "overrides"
    overrides.mkdir(parents=True)
    (overrides / "opencode.yml").write_text("services: {}\n")

    res = docker_compose.handle_compose_override_rename({
        "stack": "infra",
        "from_name": "openclaw",
        "to_name": "opencode",
        "stacks_dir": str(stacks),
    }, base_ctx)
    assert res["success"] is True
    assert res["changed"] is False


def test_compose_override_rename_missing_both_fails(tmp_path, base_ctx):
    stacks = tmp_path / "stacks"
    (stacks / "infra" / "overrides").mkdir(parents=True)
    res = docker_compose.handle_compose_override_rename({
        "stack": "infra",
        "from_name": "x",
        "to_name": "y",
        "stacks_dir": str(stacks),
    }, base_ctx)
    assert res["success"] is False


def test_volume_clone_bind_happy(tmp_path, base_ctx):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a").write_text("aa")
    (src / "sub").mkdir()
    (src / "sub" / "b").write_text("bb")
    dst = tmp_path / "dst"

    res = docker_compose.handle_volume_clone({
        "src_path": str(src), "dst_path": str(dst),
    }, base_ctx)
    assert res["success"] is True
    assert res["changed"] is True
    assert (dst / "a").read_text() == "aa"
    assert (dst / "sub" / "b").read_text() == "bb"


def test_volume_clone_bind_dst_non_empty_is_noop(tmp_path, base_ctx):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a").write_text("aa")
    dst = tmp_path / "dst"
    dst.mkdir()
    (dst / "existing").write_text("e")

    res = docker_compose.handle_volume_clone({
        "src_path": str(src), "dst_path": str(dst),
    }, base_ctx)
    assert res["success"] is True
    assert res["changed"] is False


def test_volume_clone_requires_exactly_one_mode(tmp_path, base_ctx):
    res = docker_compose.handle_volume_clone({
        "src_path": "/tmp/a", "dst_path": "/tmp/b",
        "src_volume": "a", "dst_volume": "b",
    }, base_ctx)
    assert res["success"] is False


def test_volume_clone_named_volume(tmp_path, base_ctx, fake_proc):
    calls = []

    def run_cmd(cmd):
        calls.append(list(cmd))
        if cmd[:3] == ["docker", "volume", "inspect"]:
            return fake_proc(1 if cmd[3] == "new_vol" else 0, "", "")
        if cmd[:3] == ["docker", "volume", "create"]:
            return fake_proc(0, "", "")
        if cmd[:3] == ["docker", "run", "--rm"]:
            return fake_proc(0, "", "")
        return fake_proc(0, "", "")

    base_ctx["run_cmd"] = run_cmd
    res = docker_compose.handle_volume_clone({
        "src_volume": "old_vol", "dst_volume": "new_vol",
    }, base_ctx)
    assert res["success"] is True
    assert res["changed"] is True
    # ensure volume create + run copy were invoked
    assert any(c[:3] == ["docker", "volume", "create"] for c in calls)
    assert any(c[:3] == ["docker", "run", "--rm"] for c in calls)
