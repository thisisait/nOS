"""exec.shell tests — double-gated allow_shell enforcement."""

from __future__ import absolute_import, division, print_function

from module_utils.nos_migrate_actions import exec_shell


def test_exec_shell_refuses_without_migration_flag(base_ctx, fake_proc):
    base_ctx["migration_allows_shell"] = False
    base_ctx["run_cmd"] = lambda cmd: fake_proc(0, "", "")
    res = exec_shell.handle_exec_shell(
        {"cmd": ["/bin/true"], "allow_shell": True}, base_ctx)
    assert res["success"] is False
    assert "refused" in res["error"]


def test_exec_shell_refuses_without_step_flag(base_ctx, fake_proc):
    base_ctx["migration_allows_shell"] = True
    base_ctx["run_cmd"] = lambda cmd: fake_proc(0, "", "")
    res = exec_shell.handle_exec_shell({"cmd": ["/bin/true"]}, base_ctx)
    assert res["success"] is False


def test_exec_shell_runs_when_double_gated(base_ctx, fake_proc):
    base_ctx["migration_allows_shell"] = True
    base_ctx["run_cmd"] = lambda cmd: fake_proc(0, "hi\n", "")
    res = exec_shell.handle_exec_shell(
        {"cmd": ["/bin/echo", "hi"], "allow_shell": True}, base_ctx)
    assert res["success"] is True
    assert res["changed"] is True
    assert res["result"]["rc"] == 0
    assert "hi" in res["result"]["stdout"]


def test_exec_shell_requires_list_when_shell_false(base_ctx, fake_proc):
    base_ctx["migration_allows_shell"] = True
    base_ctx["run_cmd"] = lambda cmd: fake_proc(0, "", "")
    res = exec_shell.handle_exec_shell(
        {"cmd": "echo hi", "allow_shell": True}, base_ctx)
    assert res["success"] is False
    assert "must be a list" in res["error"]


def test_exec_shell_expect_rc_mismatch(base_ctx, fake_proc):
    base_ctx["migration_allows_shell"] = True
    base_ctx["run_cmd"] = lambda cmd: fake_proc(1, "", "err")
    res = exec_shell.handle_exec_shell(
        {"cmd": ["/bin/false"], "allow_shell": True}, base_ctx)
    assert res["success"] is False
    assert "rc=1" in res["error"]
