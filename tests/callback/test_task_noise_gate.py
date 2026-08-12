"""task_start / task_skipped rows stay out of the audit chain by default.

MEASURED 2026-08-12 on the live wing.db: 332,506 event rows, 698 MB, of which
task_start (165,476) + task_skipped (120,811) were 86% — a skipped task wrote
TWO hash-chained WORM rows to say nothing happened, ~108k rows per converge
day. The chain makes every one of them permanent; pruning is a design problem
(anchor + reseal), not a DELETE, so the honest fix starts at the tap.

The contract this pins:
  * default: no task_start / task_skipped ROWS; outcome rows (ok / changed /
    failed / unreachable) keep flowing WITH durations — the timing map is
    in-memory bookkeeping, independent of emission — and the playbook_end
    recap still counts skips, so absence is counted, not narrated.
  * NOS_TELEMETRY_TASK_VERBOSE=1 restores the old per-task narration for a
    debugging run.
  * the gate must not leak: a skipped task under the default must still pop
    its timing-map entry.
"""
from __future__ import annotations

from tests.callback.conftest import (
    FakePlay, FakePlaybook, FakeResult, FakeStats, FakeTask,
)


def _drive(plugin, captured):
    plugin._http.send_batch = lambda events: captured.extend(events)
    plugin.v2_playbook_on_start(FakePlaybook("main.yml"))
    plugin.v2_playbook_on_play_start(FakePlay("p"))

    t_ok = FakeTask("does something", role="pazny.wing")
    plugin.v2_playbook_on_task_start(t_ok)
    plugin.v2_runner_on_ok(FakeResult(t_ok, {"changed": True}))

    t_skip = FakeTask("skipped by when:", role="pazny.wing")
    plugin.v2_playbook_on_task_start(t_skip)
    plugin.v2_runner_on_skipped(FakeResult(t_skip, {}))

    plugin.v2_playbook_on_stats(FakeStats({}))
    plugin._flush()


def test_default_emits_outcomes_not_narration(fresh_plugin):
    _, plugin = fresh_plugin
    captured: list = []
    _drive(plugin, captured)
    types = [e["type"] for e in captured]
    assert "task_changed" in types, "outcome rows must keep flowing"
    assert "task_start" not in types, (
        "task_start rows are back by default — 165k of them was 50% of the "
        "live events table."
    )
    assert "task_skipped" not in types, (
        "task_skipped rows are back by default — two chained rows per no-op."
    )
    changed = next(e for e in captured if e["type"] == "task_changed")
    assert changed.get("duration_ms") is not None, (
        "gating the start ROW must not gate the start TIMESTAMP — durations "
        "on outcome rows come from the in-memory map."
    )
    assert plugin._task_started_at == {}, (
        "a gated skip leaked its timing-map entry — the pop must happen "
        "whether or not the row is emitted."
    )


def test_verbose_flag_restores_narration(monkeypatch, tmp_path):
    import importlib

    monkeypatch.setenv("NOS_TELEMETRY_ENABLED", "1")
    monkeypatch.setenv("NOS_TELEMETRY_TASK_VERBOSE", "1")
    monkeypatch.setenv("WING_EVENTS_SQLITE_FALLBACK", str(tmp_path / "f.db"))
    mod = importlib.import_module("wing_telemetry")
    importlib.reload(mod)
    plugin = mod.CallbackModule()
    plugin._finalize_activation({"wing_telemetry_enabled": True})
    captured: list = []
    _drive(plugin, captured)
    types = [e["type"] for e in captured]
    assert "task_start" in types and "task_skipped" in types, (
        "NOS_TELEMETRY_TASK_VERBOSE=1 no longer restores per-task narration — "
        "the debugging path is gone, which turns the default into a ceiling."
    )
