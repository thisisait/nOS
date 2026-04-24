"""SQLite fallback: events are spilled when HTTP transport fails."""
from __future__ import annotations

import json
import sqlite3

from tests.callback.conftest import FakePlay, FakePlaybook


def test_fallback_enqueue_roundtrip(tmp_path):
    from callback_plugins import wing_telemetry as gt

    db_path = tmp_path / "fallback.db"
    fallback = gt.SQLiteFallback(str(db_path))
    events = [
        {"ts": "2026-04-22T12:00:00Z", "run_id": "run_aaa",
         "type": "task_ok"},
        {"ts": "2026-04-22T12:00:01Z", "run_id": "run_aaa",
         "type": "task_changed"},
    ]
    n = fallback.enqueue(events)
    assert n == 2
    assert fallback.count() == 2

    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT run_id, type, payload FROM fallback_events ORDER BY id"
        ).fetchall()
    finally:
        conn.close()

    assert [r[0] for r in rows] == ["run_aaa", "run_aaa"]
    assert [r[1] for r in rows] == ["task_ok", "task_changed"]
    payloads = [json.loads(r[2]) for r in rows]
    assert payloads[0]["ts"] == "2026-04-22T12:00:00Z"


def test_http_failure_spills_to_sqlite(monkeypatch, tmp_path):
    """Full-stack: flush with broken HTTP should populate the SQLite db."""
    from callback_plugins import wing_telemetry as gt

    db_path = tmp_path / "fallback.db"
    monkeypatch.setenv("NOS_TELEMETRY_ENABLED", "1")
    monkeypatch.setenv("WING_EVENTS_SQLITE_FALLBACK", str(db_path))
    monkeypatch.setenv("WING_EVENTS_BATCH_SIZE", "2")

    plugin = gt.CallbackModule()
    plugin._finalize_activation(None)

    # Swap in a transport that always fails
    class AlwaysFail:
        def send_batch(self, events):
            raise gt.TransportError("network down")

    plugin._http = AlwaysFail()

    plugin.v2_playbook_on_start(FakePlaybook("main.yml"))
    plugin.v2_playbook_on_play_start(FakePlay("p1"))
    # Force 2 events to trigger batch flush
    plugin._emit("task_ok", task="a")
    plugin._emit("task_ok", task="b")

    assert plugin._sqlite.count() >= 2

    conn = sqlite3.connect(str(db_path))
    try:
        types = [r[0] for r in conn.execute(
            "SELECT type FROM fallback_events").fetchall()]
    finally:
        conn.close()
    assert "task_ok" in types


def test_sqlite_schema_is_idempotent(tmp_path):
    """Creating the fallback twice on the same path should be a no-op."""
    from callback_plugins import wing_telemetry as gt

    p = tmp_path / "f.db"
    gt.SQLiteFallback(str(p))
    gt.SQLiteFallback(str(p))  # must not raise


def test_empty_enqueue_is_noop(tmp_path):
    from callback_plugins import wing_telemetry as gt

    fallback = gt.SQLiteFallback(str(tmp_path / "f.db"))
    assert fallback.enqueue([]) == 0
    assert fallback.count() == 0
