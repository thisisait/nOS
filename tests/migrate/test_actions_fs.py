"""Unit tests for fs.* action handlers."""

from __future__ import absolute_import, division, print_function

import os

import pytest

from module_utils.nos_migrate_actions import fs as fs_actions


# ---------------------------------------------------------------------------
# fs.mv

def test_fs_mv_happy_path(tmp_path, base_ctx):
    src = tmp_path / "a"
    src.mkdir()
    (src / "f.txt").write_text("hello")
    dst = tmp_path / "b"

    res = fs_actions.handle_mv({"src": str(src), "dst": str(dst)}, base_ctx)
    assert res["success"] is True
    assert res["changed"] is True
    assert not src.exists()
    assert (dst / "f.txt").read_text() == "hello"


def test_fs_mv_idempotent_when_already_moved(tmp_path, base_ctx):
    dst = tmp_path / "b"
    dst.mkdir()
    src = tmp_path / "a"
    # src does not exist, dst does → changed=False
    res = fs_actions.handle_mv({"src": str(src), "dst": str(dst)}, base_ctx)
    assert res["success"] is True
    assert res["changed"] is False


def test_fs_mv_refuses_overwrite_by_default(tmp_path, base_ctx):
    src = tmp_path / "a"
    src.mkdir()
    dst = tmp_path / "b"
    dst.mkdir()
    res = fs_actions.handle_mv({"src": str(src), "dst": str(dst)}, base_ctx)
    assert res["success"] is False


def test_fs_mv_overwrite(tmp_path, base_ctx):
    src = tmp_path / "a"
    src.mkdir()
    (src / "marker").write_text("new")
    dst = tmp_path / "b"
    dst.mkdir()
    (dst / "stale").write_text("old")

    res = fs_actions.handle_mv(
        {"src": str(src), "dst": str(dst), "overwrite": True}, base_ctx)
    assert res["success"] is True
    assert (dst / "marker").read_text() == "new"
    assert not (dst / "stale").exists()


def test_fs_mv_dry_run(tmp_path, base_ctx):
    src = tmp_path / "a"
    src.mkdir()
    dst = tmp_path / "b"
    base_ctx["dry_run"] = True
    res = fs_actions.handle_mv({"src": str(src), "dst": str(dst)}, base_ctx)
    assert res["success"] is True
    assert res["changed"] is True
    # side-effect-free
    assert src.exists()
    assert not dst.exists()


# ---------------------------------------------------------------------------
# fs.cp

def test_fs_cp_recursive(tmp_path, base_ctx):
    src = tmp_path / "src"
    src.mkdir()
    (src / "f").write_text("x")
    dst = tmp_path / "dst"
    res = fs_actions.handle_cp({"src": str(src), "dst": str(dst)}, base_ctx)
    assert res["success"] is True
    assert res["changed"] is True
    assert (dst / "f").read_text() == "x"
    assert src.exists()  # src preserved


def test_fs_cp_idempotent(tmp_path, base_ctx):
    src = tmp_path / "src"
    src.mkdir()
    dst = tmp_path / "dst"
    dst.mkdir()
    res = fs_actions.handle_cp({"src": str(src), "dst": str(dst)}, base_ctx)
    assert res["success"] is True
    assert res["changed"] is False


# ---------------------------------------------------------------------------
# fs.rm

def test_fs_rm_happy(tmp_path, base_ctx):
    p = tmp_path / "doomed"
    p.mkdir()
    (p / "f").write_text("bye")
    res = fs_actions.handle_rm({"path": str(p)}, base_ctx)
    assert res["success"] is True
    assert res["changed"] is True
    assert not p.exists()


def test_fs_rm_missing_ok(tmp_path, base_ctx):
    p = tmp_path / "never_existed"
    res = fs_actions.handle_rm({"path": str(p)}, base_ctx)
    assert res["success"] is True
    assert res["changed"] is False


def test_fs_rm_missing_not_ok(tmp_path, base_ctx):
    p = tmp_path / "never_existed"
    res = fs_actions.handle_rm(
        {"path": str(p), "missing_ok": False}, base_ctx)
    assert res["success"] is False


# ---------------------------------------------------------------------------
# fs.ensure_dir

def test_fs_ensure_dir_creates(tmp_path, base_ctx):
    p = tmp_path / "a" / "b" / "c"
    res = fs_actions.handle_ensure_dir({"path": str(p)}, base_ctx)
    assert res["success"] is True
    assert res["changed"] is True
    assert p.is_dir()


def test_fs_ensure_dir_idempotent(tmp_path, base_ctx):
    p = tmp_path / "exists"
    p.mkdir()
    res = fs_actions.handle_ensure_dir({"path": str(p)}, base_ctx)
    assert res["success"] is True
    assert res["changed"] is False


def test_fs_ensure_dir_fails_if_file(tmp_path, base_ctx):
    p = tmp_path / "f"
    p.write_text("not a dir")
    res = fs_actions.handle_ensure_dir({"path": str(p)}, base_ctx)
    assert res["success"] is False


def test_fs_ensure_dir_sets_mode(tmp_path, base_ctx):
    p = tmp_path / "m"
    res = fs_actions.handle_ensure_dir(
        {"path": str(p), "mode": "0700"}, base_ctx)
    assert res["success"] is True
    have = os.stat(p).st_mode & 0o777
    assert have == 0o700
