"""Run-id stability, playbook_start/end pairing, activation toggles,
scrubbing, and synthetic migration/upgrade context extraction."""
from __future__ import annotations

import os

from tests.callback.conftest import (FakePlay, FakePlaybook, FakeResult,
                                      FakeStats, FakeTask)


# --------------------------------------------------------------------------- #
# Activation                                                                  #
# --------------------------------------------------------------------------- #

def test_inactive_by_default_is_noop(monkeypatch, tmp_path):
    """No env var, no play var -> every callback is a zero-overhead no-op."""
    from callback_plugins import glasswing_telemetry as gt

    plugin = gt.CallbackModule()
    assert plugin._active is False

    captured = []

    class Sentinel:
        def send_batch(self, events):
            captured.append(events)

    plugin._http = Sentinel()
    plugin.v2_playbook_on_start(FakePlaybook("main.yml"))
    plugin.v2_playbook_on_play_start(FakePlay("p"))
    t = FakeTask("anything")
    plugin.v2_playbook_on_task_start(t)
    plugin.v2_runner_on_ok(FakeResult(t, {"changed": False}))
    plugin.v2_playbook_on_stats(FakeStats({}))

    assert plugin._active is False
    assert captured == []
    assert plugin._buffer == []


def test_env_var_activates(monkeypatch, tmp_path):
    from callback_plugins import glasswing_telemetry as gt

    monkeypatch.setenv("NOS_TELEMETRY_ENABLED", "1")
    monkeypatch.setenv("GLASSWING_EVENTS_SQLITE_FALLBACK",
                       str(tmp_path / "f.db"))
    plugin = gt.CallbackModule()
    plugin.v2_playbook_on_start(FakePlaybook("main.yml"))
    assert plugin._active is True


def test_play_var_activates(tmp_path, monkeypatch):
    from callback_plugins import glasswing_telemetry as gt

    monkeypatch.setenv("GLASSWING_EVENTS_SQLITE_FALLBACK",
                       str(tmp_path / "f.db"))
    plugin = gt.CallbackModule()
    plugin.v2_playbook_on_start(FakePlaybook("main.yml"))
    assert plugin._active is False
    # playbook_on_start was a no-op; play activates it
    captured = []

    plugin.v2_playbook_on_play_start(
        FakePlay("p1", vars_={"glasswing_telemetry_enabled": True}))
    if plugin._http is not None:
        plugin._http.send_batch = lambda events: captured.extend(events)
    assert plugin._active is True


# --------------------------------------------------------------------------- #
# run_id stability                                                            #
# --------------------------------------------------------------------------- #

def test_run_id_stable_across_events(fresh_plugin):
    _, plugin = fresh_plugin
    captured = []
    plugin._http.send_batch = lambda events: captured.extend(events)

    plugin.v2_playbook_on_start(FakePlaybook("main.yml"))
    plugin.v2_playbook_on_play_start(FakePlay("p"))
    for i in range(5):
        t = FakeTask(f"task-{i}")
        plugin.v2_playbook_on_task_start(t)
        plugin.v2_runner_on_ok(FakeResult(t, {"changed": False}))
    plugin.v2_playbook_on_stats(FakeStats({"localhost": {
        "ok": 5, "changed": 0, "failed": 0, "skipped": 0,
        "unreachable": 0, "rescued": 0, "ignored": 0}}))

    run_ids = {ev["run_id"] for ev in captured}
    assert len(run_ids) == 1
    only_run = next(iter(run_ids))
    assert only_run.startswith("run_")


def test_different_plugin_instances_have_distinct_run_ids(fresh_plugin,
                                                          monkeypatch,
                                                          tmp_path):
    from callback_plugins import glasswing_telemetry as gt

    _, plugin1 = fresh_plugin
    plugin2 = gt.CallbackModule()
    assert plugin1._run_id != plugin2._run_id


# --------------------------------------------------------------------------- #
# playbook_start / playbook_end pairing                                       #
# --------------------------------------------------------------------------- #

def test_playbook_start_and_end_pair(fresh_plugin):
    _, plugin = fresh_plugin
    captured = []
    plugin._http.send_batch = lambda events: captured.extend(events)

    plugin.v2_playbook_on_start(FakePlaybook("main.yml"))
    plugin.v2_playbook_on_play_start(FakePlay("p"))
    plugin.v2_playbook_on_stats(FakeStats({"localhost": {
        "ok": 0, "changed": 0, "failed": 0, "skipped": 0,
        "unreachable": 0, "rescued": 0, "ignored": 0}}))

    types = [ev["type"] for ev in captured]
    assert types.count("playbook_start") == 1
    assert types.count("playbook_end") == 1
    assert types.index("playbook_start") < types.index("playbook_end")
    end = [ev for ev in captured if ev["type"] == "playbook_end"][0]
    assert end["recap"] is not None
    assert end["duration_ms"] is not None and end["duration_ms"] >= 0


# --------------------------------------------------------------------------- #
# Scrubbing                                                                   #
# --------------------------------------------------------------------------- #

def test_scrub_removes_sensitive_keys():
    from callback_plugins import glasswing_telemetry as gt

    src = {
        "msg": "ok",
        "password": "hunter2",
        "api_token": "abc",
        "nested": {"secret_key": "xyz", "keep": 1},
        "list": [{"auth_token": "t"}, "plain"],
    }
    out = gt.scrub(src)
    assert out["password"] == "***"
    assert out["api_token"] == "***"
    assert out["nested"]["secret_key"] == "***"
    assert out["nested"]["keep"] == 1
    assert out["list"][0]["auth_token"] == "***"
    assert out["list"][1] == "plain"
    # original untouched
    assert src["password"] == "hunter2"


def test_runner_on_ok_scrubs_result(fresh_plugin):
    _, plugin = fresh_plugin
    captured = []
    plugin._http.send_batch = lambda events: captured.extend(events)

    plugin.v2_playbook_on_start(FakePlaybook("main.yml"))
    plugin.v2_playbook_on_play_start(FakePlay("p"))
    t = FakeTask("secret task")
    plugin.v2_playbook_on_task_start(t)
    plugin.v2_runner_on_ok(FakeResult(t, {
        "changed": True, "msg": "ok", "password": "s3cret",
        "api_key": "k",
    }))
    plugin._flush()

    task_ok = [ev for ev in captured if ev["type"] == "task_changed"][0]
    assert task_ok["result"]["password"] == "***"
    assert task_ok["result"]["api_key"] == "***"
    assert task_ok["result"]["msg"] == "ok"


# --------------------------------------------------------------------------- #
# Synthetic migration / upgrade / coexistence context                         #
# --------------------------------------------------------------------------- #

def test_migration_id_extracted_from_task_name(fresh_plugin):
    _, plugin = fresh_plugin
    captured = []
    plugin._http.send_batch = lambda events: captured.extend(events)

    plugin.v2_playbook_on_start(FakePlaybook("main.yml"))
    plugin.v2_playbook_on_play_start(FakePlay("p"))

    t = FakeTask("[Migrate] 2026-04-22-devboxnos-to-nos — rename state dir")
    plugin.v2_playbook_on_task_start(t)
    plugin.v2_runner_on_ok(FakeResult(t, {"changed": False}))
    plugin._flush()

    task_ok = [ev for ev in captured if ev["type"] == "task_ok"][0]
    assert task_ok["migration_id"] == "2026-04-22-devboxnos-to-nos"


def test_upgrade_id_extracted(fresh_plugin):
    _, plugin = fresh_plugin
    captured = []
    plugin._http.send_batch = lambda events: captured.extend(events)

    plugin.v2_playbook_on_start(FakePlaybook("main.yml"))
    plugin.v2_playbook_on_play_start(FakePlay("p"))
    t = FakeTask("[Upgrade] grafana-11-to-12 apply image bump")
    plugin.v2_playbook_on_task_start(t)
    plugin.v2_runner_on_ok(FakeResult(t, {"changed": True}))
    plugin._flush()

    ev = [e for e in captured if e["type"] == "task_changed"][0]
    assert ev["upgrade_id"] == "grafana-11-to-12"


def test_coexistence_service_extracted(fresh_plugin):
    _, plugin = fresh_plugin
    captured = []
    plugin._http.send_batch = lambda events: captured.extend(events)

    plugin.v2_playbook_on_start(FakePlaybook("main.yml"))
    plugin.v2_playbook_on_play_start(FakePlay("p"))
    t = FakeTask("[Coexistence] grafana provision new track")
    plugin.v2_playbook_on_task_start(t)
    plugin.v2_runner_on_ok(FakeResult(t, {"changed": False}))
    plugin._flush()

    ev = [e for e in captured if e["type"] == "task_ok"][0]
    assert ev["coexistence_service"] == "grafana"


def test_no_tag_leaves_context_null(fresh_plugin):
    _, plugin = fresh_plugin
    captured = []
    plugin._http.send_batch = lambda events: captured.extend(events)

    plugin.v2_playbook_on_start(FakePlaybook("main.yml"))
    plugin.v2_playbook_on_play_start(FakePlay("p"))
    t = FakeTask("regular task")
    plugin.v2_playbook_on_task_start(t)
    plugin.v2_runner_on_ok(FakeResult(t, {"changed": False}))
    plugin._flush()

    ev = [e for e in captured if e["type"] == "task_ok"][0]
    assert ev["migration_id"] is None
    assert ev["upgrade_id"] is None
    assert ev["coexistence_service"] is None


# --------------------------------------------------------------------------- #
# Batching                                                                    #
# --------------------------------------------------------------------------- #

def test_batch_flushes_on_size(monkeypatch, tmp_path):
    from callback_plugins import glasswing_telemetry as gt

    monkeypatch.setenv("NOS_TELEMETRY_ENABLED", "1")
    monkeypatch.setenv("GLASSWING_EVENTS_SQLITE_FALLBACK",
                       str(tmp_path / "f.db"))
    monkeypatch.setenv("GLASSWING_EVENTS_BATCH_SIZE", "3")
    monkeypatch.setenv("GLASSWING_EVENTS_FLUSH_INTERVAL_SEC", "3600")

    plugin = gt.CallbackModule()
    plugin._finalize_activation(None)

    batches = []

    class Collect:
        def send_batch(self, events):
            batches.append(list(events))

    plugin._http = Collect()

    plugin.v2_playbook_on_start(FakePlaybook("main.yml"))  # 1 event
    plugin.v2_playbook_on_play_start(FakePlay("p"))        # 2 events
    plugin._emit("task_ok", task="x")                       # 3 -> flush
    plugin._emit("task_ok", task="y")

    assert batches, "expected at least one flush"
    assert len(batches[0]) == 3


def test_debug_mode_flushes_immediately(monkeypatch, tmp_path):
    from callback_plugins import glasswing_telemetry as gt

    monkeypatch.setenv("NOS_TELEMETRY_ENABLED", "1")
    monkeypatch.setenv("GLASSWING_EVENTS_DEBUG", "1")
    monkeypatch.setenv("GLASSWING_EVENTS_SQLITE_FALLBACK",
                       str(tmp_path / "f.db"))

    plugin = gt.CallbackModule()
    plugin._finalize_activation(None)

    batches = []

    class Collect:
        def send_batch(self, events):
            batches.append(list(events))

    plugin._http = Collect()
    plugin.v2_playbook_on_start(FakePlaybook("main.yml"))

    # Debug mode should have flushed after the single event.
    assert batches, "debug mode should flush immediately"
    assert len(batches[0]) == 1


def test_tagged_id_extraction_helper():
    from callback_plugins import glasswing_telemetry as gt

    assert gt.extract_tagged_id("[Migrate] abc-123",
                                 gt._MIGRATION_TAG_RE) == "abc-123"
    assert gt.extract_tagged_id("[Migrate] abc-123 — move stuff",
                                 gt._MIGRATION_TAG_RE) == "abc-123"
    assert gt.extract_tagged_id("no tag", gt._MIGRATION_TAG_RE) is None
    assert gt.extract_tagged_id("[Upgrade] grafana",
                                 gt._MIGRATION_TAG_RE) is None
    assert gt.extract_tagged_id("[Upgrade] grafana",
                                 gt._UPGRADE_TAG_RE) == "grafana"
    assert gt.extract_tagged_id("[Coexist] gitea",
                                 gt._COEXIST_TAG_RE) == "gitea"
    assert gt.extract_tagged_id("[Coexistence] gitea",
                                 gt._COEXIST_TAG_RE) == "gitea"
