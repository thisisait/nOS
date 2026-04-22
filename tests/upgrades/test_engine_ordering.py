"""Simulated engine loop: verify pre -> apply -> post -> (rollback on post
failure) ordering. Exercises the merged dispatch table."""

from __future__ import absolute_import, division, print_function

from module_utils import nos_upgrade_actions as uc


def _sim_run_steps(steps, ctx, trace, handlers):
    """Mini engine loop: dispatch each step, record, fail on first non-success."""
    for step in steps:
        stype = step["type"]
        handler = handlers[stype]
        trace.append("call:%s:%s" % (step["id"], stype))
        res = handler(step, ctx)
        trace.append("done:%s:%s:%s" % (step["id"], stype,
                                        "ok" if res.get("success") else "FAIL"))
        if not res.get("success"):
            return False, res
    return True, None


def _sim_recipe(recipe, ctx, handlers):
    """Walk pre -> apply -> post; on post failure, run rollback in order."""
    trace = []
    for phase in ("pre", "apply", "post"):
        trace.append("phase:%s" % phase)
        ok, _ = _sim_run_steps(recipe.get(phase, []), ctx, trace, handlers)
        if not ok:
            if phase == "post":
                trace.append("phase:rollback")
                _sim_run_steps(recipe.get("rollback", []), ctx, trace, handlers)
                return {"success": False, "rolled_back": True, "trace": trace}
            return {"success": False, "rolled_back": False, "trace": trace,
                    "failed_phase": phase}
    return {"success": True, "rolled_back": False, "trace": trace}


def _make_handlers(inject_failing=None):
    """Return a minimal handler table with stub noop + injectable failers."""
    handlers = {}

    def ok(action, ctx):
        return {"success": True, "changed": True, "result": {"id": action.get("id")}}

    def fail(action, ctx):
        return {"success": False, "changed": False,
                "error": "injected failure for %s" % action.get("id")}

    def dispatch(action, ctx):
        if inject_failing and action.get("id") in inject_failing:
            return fail(action, ctx)
        return ok(action, ctx)

    for t in ("backup.volume", "backup.restore", "http.wait", "http.get_all",
              "compose.set_image_tag", "compose.restart_service",
              "custom.module", "fs.mv", "fs.cp", "fs.rm", "fs.ensure_dir",
              "exec.shell", "noop"):
        handlers[t] = dispatch
    return handlers


def _grafana_recipe_shape():
    return {
        "id": "grafana-11-to-12",
        "pre": [
            {"id": "backup_data",       "type": "backup.volume"},
            {"id": "export_dashboards", "type": "http.get_all"},
        ],
        "apply": [
            {"id": "bump_image_tag", "type": "compose.set_image_tag"},
        ],
        "post": [
            {"id": "wait_healthy",           "type": "http.wait"},
            {"id": "dashboard_render_check", "type": "custom.module"},
        ],
        "rollback": [
            {"id": "revert_image_tag", "type": "compose.set_image_tag"},
            {"id": "restore_data",     "type": "backup.restore"},
        ],
    }


def test_happy_path_runs_pre_apply_post_in_order():
    out = _sim_recipe(_grafana_recipe_shape(), {}, _make_handlers())
    assert out["success"]
    assert not out["rolled_back"]
    # Phase markers appear in the right sequence.
    phases = [line for line in out["trace"] if line.startswith("phase:")]
    assert phases == ["phase:pre", "phase:apply", "phase:post"]
    # Within pre, backup precedes dashboard export.
    calls = [line for line in out["trace"] if line.startswith("call:")]
    ids = [c.split(":")[1] for c in calls]
    assert ids == ["backup_data", "export_dashboards", "bump_image_tag",
                   "wait_healthy", "dashboard_render_check"]


def test_failure_during_apply_does_not_run_rollback():
    handlers = _make_handlers(inject_failing={"bump_image_tag"})
    out = _sim_recipe(_grafana_recipe_shape(), {}, handlers)
    assert not out["success"]
    assert not out["rolled_back"]
    assert out["failed_phase"] == "apply"


def test_failure_during_post_triggers_rollback():
    handlers = _make_handlers(inject_failing={"wait_healthy"})
    out = _sim_recipe(_grafana_recipe_shape(), {}, handlers)
    assert not out["success"]
    assert out["rolled_back"]
    calls = [line.split(":")[1] for line in out["trace"] if line.startswith("call:")]
    # pre + apply + failing post step, then rollback steps in order.
    assert calls == ["backup_data", "export_dashboards", "bump_image_tag",
                     "wait_healthy", "revert_image_tag", "restore_data"]


def test_second_post_step_failure_also_triggers_rollback():
    handlers = _make_handlers(inject_failing={"dashboard_render_check"})
    out = _sim_recipe(_grafana_recipe_shape(), {}, handlers)
    assert not out["success"]
    assert out["rolled_back"]


def test_merged_handlers_has_both_tables():
    merged = uc.merged_handlers()
    # Upgrade handlers present.
    for t in ("backup.volume", "backup.restore", "http.wait", "http.get_all",
              "compose.set_image_tag", "compose.restart_service",
              "custom.module"):
        assert t in merged, "missing upgrade handler %r" % t
    # Migration handlers present (from agent 2's table).  We assert a
    # representative sample rather than the full list — agent 2 owns that.
    for t in ("fs.mv", "fs.cp", "fs.rm", "fs.ensure_dir", "noop"):
        assert t in merged, "missing migration handler %r" % t
