"""W6.1 (2026-06-10): playbook-failure notification emitter.

A failed playbook run must land ONE high-severity notification in the Wing
inbox via Bone ``/api/v1/notifications`` — the events pipeline records every
task but nothing watched the recap, so the operator-attention surface stayed
empty while ``failed=3`` scrolled past in ansible.log.

Contract pinned here:
  - HTTPTransport.send_object posts a SINGLE canonical-JSON object to the
    GIVEN url (not the transport's events url) with the same bare-hex HMAC
    scheme Bone verifies (ts + "." + body).
  - v2_playbook_on_stats emits exactly one notification when failed or
    unreachable > 0, none on a clean run.
  - the emit is best-effort: a transport error never raises out of the
    stats callback.
"""
from __future__ import annotations

import hashlib
import hmac as hmac_mod
import json

from tests.callback.test_http_transport import FakeRequests, FakeResponse


def _activated_plugin(gt, monkeypatch, tmp_path):
    monkeypatch.setenv("NOS_TELEMETRY_ENABLED", "1")
    monkeypatch.setenv("WING_EVENTS_SQLITE_FALLBACK", str(tmp_path / "f.db"))
    monkeypatch.setenv("NOS_PLAYBOOK_JSONL_PATH", str(tmp_path / "pb.jsonl"))
    plugin = gt.CallbackModule()
    return plugin


class FakeStats:
    def __init__(self, failed=0, unreachable=0, ok=5):
        self.processed = {"localhost": 1}
        # Ansible's AggregateStats.summarize() says `failures`, not `failed`.
        # This fixture said `failed` — the same slip as the callback — so the
        # gate passed while a real failed run never raised the notification.
        self._summary = {
            "ok": ok, "changed": 1, "failures": failed, "skipped": 0,
            "unreachable": unreachable, "rescued": 0, "ignored": 0,
        }

    def summarize(self, _host):
        return dict(self._summary)


def test_send_object_posts_to_given_url_with_hmac():
    from callback_plugins import wing_telemetry as gt

    fake = FakeRequests([FakeResponse(201)])
    tr = gt.HTTPTransport(url="http://example/api/v1/events",
                          secret="topsecret",
                          session=fake, max_retries=1, backoff_base=0.0)
    payload = {"severity": "high", "title": "t"}
    tr.send_object("http://example/api/v1/notifications", payload)

    assert len(fake.calls) == 1
    call = fake.calls[0]
    # Posts to the GIVEN url, not the events url baked into the transport.
    assert call["url"] == "http://example/api/v1/notifications"
    body = call["data"]
    assert json.loads(body) == payload
    # Canonical serialisation — Bone re-serialises sort_keys+compact and
    # verifies the HMAC byte-for-byte.
    assert body == json.dumps(payload, separators=(",", ":"),
                              sort_keys=True).encode("utf-8")
    ts = call["headers"]["X-Wing-Timestamp"]
    expect = hmac_mod.new(b"topsecret", ts.encode() + b"." + body,
                          hashlib.sha256).hexdigest()
    assert call["headers"]["X-Wing-Signature"] == expect


def test_failed_run_emits_one_high_notification(monkeypatch, tmp_path):
    from callback_plugins import wing_telemetry as gt

    plugin = _activated_plugin(gt, monkeypatch, tmp_path)

    sent = []

    class Sentinel:
        def send_batch(self, events):
            pass

        def send_object(self, url, obj):
            sent.append((url, obj))

    plugin._http = Sentinel()
    plugin._active = True
    plugin._playbook_name = "main.yml"

    plugin.v2_playbook_on_stats(FakeStats(failed=2, unreachable=1))

    assert len(sent) == 1
    url, obj = sent[0]
    assert url.endswith("/api/v1/notifications")
    assert obj["severity"] == "high"
    assert "2 failed" in obj["title"] and "1 unreachable" in obj["title"]
    assert obj["actor_action_id"] == plugin._run_id


def test_clean_run_emits_nothing(monkeypatch, tmp_path):
    from callback_plugins import wing_telemetry as gt

    plugin = _activated_plugin(gt, monkeypatch, tmp_path)

    sent = []

    class Sentinel:
        def send_batch(self, events):
            pass

        def send_object(self, url, obj):
            sent.append((url, obj))

    plugin._http = Sentinel()
    plugin._active = True
    plugin._playbook_name = "main.yml"

    plugin.v2_playbook_on_stats(FakeStats(failed=0, unreachable=0))
    assert sent == []


def test_notification_transport_error_is_swallowed(monkeypatch, tmp_path):
    from callback_plugins import wing_telemetry as gt

    plugin = _activated_plugin(gt, monkeypatch, tmp_path)

    class Exploding:
        def send_batch(self, events):
            pass

        def send_object(self, url, obj):
            raise gt.TransportError("bone down")

    plugin._http = Exploding()
    plugin._active = True
    plugin._playbook_name = "main.yml"

    # Must not raise — best-effort by design.
    plugin.v2_playbook_on_stats(FakeStats(failed=1))


def test_notifications_url_env_override(monkeypatch, tmp_path):
    from callback_plugins import wing_telemetry as gt

    plugin = _activated_plugin(gt, monkeypatch, tmp_path)
    monkeypatch.setenv("WING_NOTIFICATIONS_URL",
                       "http://other:1234/api/v1/notifications")

    sent = []

    class Sentinel:
        def send_batch(self, events):
            pass

        def send_object(self, url, obj):
            sent.append(url)

    plugin._http = Sentinel()
    plugin._active = True
    plugin._playbook_name = "main.yml"

    plugin.v2_playbook_on_stats(FakeStats(failed=1))
    assert sent == ["http://other:1234/api/v1/notifications"]


# 2026-10-05: 11 unread HIGH "Playbook run failed" rows outlived the green
# converges after them — the emitter sent no supersede_key, so nothing could
# retire them. The next run's outcome is the current word on this host.

def _capture(gt, monkeypatch, tmp_path, cliargs):
    plugin = _activated_plugin(gt, monkeypatch, tmp_path)
    monkeypatch.setattr(gt, "_cliargs", lambda: cliargs, raising=False)
    sent = []

    class Sentinel:
        def send_batch(self, events):
            pass

        def send_object(self, url, obj):
            sent.append(obj)

    plugin._http = Sentinel()
    plugin._active = True
    plugin._playbook_name = "main.yml"
    return plugin, sent


FULL = {"tags": ("all",), "skip_tags": (), "subset": None}


def test_failure_and_green_share_one_supersede_class(monkeypatch, tmp_path):
    from callback_plugins import wing_telemetry as gt

    plugin, sent = _capture(gt, monkeypatch, tmp_path, FULL)
    plugin.v2_playbook_on_stats(FakeStats(failed=1))
    plugin.v2_playbook_on_stats(FakeStats(failed=0))
    assert [o["severity"] for o in sent] == ["high", "info"]
    keys = {o.get("supersede_key") for o in sent}
    assert len(keys) == 1 and next(iter(keys)).startswith("playbook-run:"), keys
    assert {o.get("origin_plugin") for o in sent} == {"playbook-run"}
    import re
    assert re.match(r"^[a-z0-9][a-z0-9_.:-]{0,62}[a-z0-9]$", sent[0]["supersede_key"])


def test_a_scoped_green_run_claims_nothing(monkeypatch, tmp_path):
    """`--tags nginx` green never re-ran the task that failed; nor did a run that
    started mid-play, stepped (tasks may be declined) or only checked."""
    from callback_plugins import wing_telemetry as gt

    for scoped in ({**FULL, "tags": ("nginx",)}, {**FULL, "skip_tags": ("stacks",)},
                   {**FULL, "subset": "localhost"}, {},
                   {**FULL, "start_at_task": "Install nginx"}, {**FULL, "step": True},
                   {**FULL, "check": True}):
        _, sent = _capture(gt, monkeypatch, tmp_path, scoped)
        _.v2_playbook_on_stats(FakeStats(failed=0))
        assert sent == [], scoped
