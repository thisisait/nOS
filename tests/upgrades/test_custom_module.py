"""custom.module — deferred directive + injector paths."""

from __future__ import absolute_import, division, print_function

from module_utils.nos_upgrade_actions import custom_module as cm


def test_missing_module_fails(base_ctx):
    res = cm.handle_custom_module({}, base_ctx)
    assert not res["success"]


def test_bad_args_type_fails(base_ctx):
    res = cm.handle_custom_module(
        {"module": "ansible.builtin.uri", "args": "not a dict"},
        base_ctx,
    )
    assert not res["success"]


def test_deferred_directive_default(base_ctx):
    res = cm.handle_custom_module(
        {"module": "ansible.builtin.uri",
         "args": {"url": "https://x", "return_content": True},
         "register_as": "_out",
         "ignore_errors": True},
        base_ctx,
    )
    assert res["success"]
    assert not res["changed"]
    assert res["result"]["deferred"] is True
    assert res["result"]["module"] == "ansible.builtin.uri"
    assert res["result"]["register_as"] == "_out"
    assert res["result"]["ignore_errors"] is True


def test_injector_is_called_when_present(base_ctx):
    seen = {}

    def _injector(module, args, ctx):
        seen["module"] = module
        seen["args"] = dict(args)
        return {"success": True, "changed": True, "status_code": 204}

    base_ctx["invoke_module"] = _injector
    res = cm.handle_custom_module(
        {"module": "ansible.builtin.uri", "args": {"url": "https://x"}},
        base_ctx,
    )
    assert res["success"] and res["changed"]
    assert res["result"]["status_code"] == 204
    assert seen["module"] == "ansible.builtin.uri"


def test_injector_propagates_failure(base_ctx):
    base_ctx["invoke_module"] = lambda **kw: {"success": False, "error": "boom"}
    res = cm.handle_custom_module(
        {"module": "m.x", "args": {}},
        base_ctx,
    )
    assert not res["success"]
    assert res["error"] == "boom"


def test_dry_run_returns_deferred_with_flag(base_ctx):
    base_ctx["dry_run"] = True
    res = cm.handle_custom_module(
        {"module": "ansible.builtin.debug", "args": {"msg": "hi"}},
        base_ctx,
    )
    assert res["success"]
    assert not res["changed"]
    assert res["result"]["deferred"] is True
    assert res["result"]["dry_run"] is True
