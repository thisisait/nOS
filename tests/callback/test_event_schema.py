"""Validate that every event type the plugin emits conforms to the JSON schema.

These tests use the plugin's own ``_make_event`` helper so the test suite
tracks the real shape of emitted events. Any new event type must be added
here.
"""
from __future__ import annotations

import pytest

from tests.callback.conftest import (FakePlay, FakePlaybook, FakeResult,
                                      FakeStats, FakeTask)


EVENT_TYPES = [
    "playbook_start", "playbook_end",
    "play_start", "play_end",
    "task_start", "task_ok", "task_changed", "task_failed",
    "task_skipped", "task_unreachable",
    "handler_start", "handler_ok",
    "migration_start", "migration_step_ok", "migration_step_failed",
    "migration_end",
    "upgrade_start", "upgrade_step_ok", "upgrade_end",
    "coexistence_provision", "coexistence_cutover", "coexistence_cleanup",
]


def test_minimal_event_validates(validator, fresh_plugin):
    _, plugin = fresh_plugin
    ev = plugin._make_event("playbook_start", playbook="main.yml")
    errors = list(validator.iter_errors(ev))
    assert errors == [], errors


@pytest.mark.parametrize("event_type", EVENT_TYPES)
def test_every_event_type_validates(validator, fresh_plugin, event_type):
    _, plugin = fresh_plugin
    ev = plugin._make_event(event_type, task="demo", host="localhost",
                            duration_ms=12, changed=True, result={"ok": 1})
    errors = list(validator.iter_errors(ev))
    assert errors == [], "type={} errors={}".format(event_type, errors)


def test_run_id_matches_pattern(validator, fresh_plugin):
    _, plugin = fresh_plugin
    ev = plugin._make_event("playbook_start")
    assert ev["run_id"].startswith("run_")
    errors = list(validator.iter_errors(ev))
    assert errors == []


def test_invalid_event_type_is_rejected(validator):
    from datetime import datetime, timezone
    bad = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "run_id": "run_00000000-0000-0000-0000-000000000000",
        "type": "not_a_real_type",
    }
    errors = list(validator.iter_errors(bad))
    assert errors, "bogus type should have failed validation"


def test_recap_on_playbook_end_validates(validator, fresh_plugin):
    _, plugin = fresh_plugin
    ev = plugin._make_event(
        "playbook_end",
        playbook="main.yml",
        duration_ms=1000,
        recap={"ok": 10, "changed": 2, "failed": 0,
               "skipped": 1, "unreachable": 0,
               "rescued": 0, "ignored": 0},
    )
    errors = list(validator.iter_errors(ev))
    assert errors == [], errors


def test_extra_properties_are_rejected(validator, fresh_plugin):
    _, plugin = fresh_plugin
    ev = plugin._make_event("task_ok")
    ev["bogus_extra"] = "nope"
    errors = list(validator.iter_errors(ev))
    assert errors, "additionalProperties: false should reject extras"


# --------------------------------------------------------------------------- #
# End-to-end: run a tiny play through the callback and verify every          #
# captured payload validates.                                                 #
# --------------------------------------------------------------------------- #

def test_full_playbook_lifecycle_validates(validator, fresh_plugin):
    mod, plugin = fresh_plugin

    captured = []

    def capture(events):
        captured.extend(events)

    plugin._http.send_batch = capture  # type: ignore[assignment]

    plugin.v2_playbook_on_start(FakePlaybook("main.yml"))
    plugin.v2_playbook_on_play_start(FakePlay("host preflight"))

    t1 = FakeTask("[Migrate] 2026-04-22-devboxnos-to-nos", role="state_manager")
    plugin.v2_playbook_on_task_start(t1)
    plugin.v2_runner_on_ok(FakeResult(t1, {"changed": True, "msg": "ok"}))

    t2 = FakeTask("some task that skips")
    plugin.v2_playbook_on_task_start(t2)
    plugin.v2_runner_on_skipped(FakeResult(t2, {"skipped": True}))

    t3 = FakeTask("failing task")
    plugin.v2_playbook_on_task_start(t3)
    plugin.v2_runner_on_failed(FakeResult(t3, {"msg": "boom"}))

    t4 = FakeTask("unreachable")
    plugin.v2_playbook_on_task_start(t4)
    plugin.v2_runner_on_unreachable(FakeResult(t4, {"unreachable": True}))

    h = FakeTask("restart nginx")
    plugin.v2_playbook_on_handler_task_start(h)

    plugin.v2_playbook_on_stats(FakeStats({
        "localhost": {"ok": 4, "changed": 1, "failed": 1,
                      "skipped": 1, "unreachable": 1,
                      "rescued": 0, "ignored": 0}
    }))

    assert captured, "expected at least one event to be sent"
    for ev in captured:
        errors = list(validator.iter_errors(ev))
        assert errors == [], "type={} errors={}".format(ev.get("type"), errors)

    types = [ev["type"] for ev in captured]
    assert "playbook_start" in types
    assert "playbook_end" in types
    assert "task_changed" in types
    assert "task_skipped" in types
    assert "task_failed" in types
    assert "task_unreachable" in types
    assert "handler_start" in types

    # migration_id should be extracted from the [Migrate] tag
    migration_events = [ev for ev in captured
                        if ev["migration_id"] is not None]
    assert migration_events, "expected migration_id to be extracted"
    assert migration_events[0]["migration_id"] == \
        "2026-04-22-devboxnos-to-nos"
