"""Robustness (2026-07-17): telemetry must never slow or wedge the playbook.

Regression cover for the live incident where an HMAC secret desync between the
callback and Bone made every event 401 → every event spilled to an unbounded
/tmp SQLite db that grew to 258 MB and crawled the run (minutes per write).

Guards:
  1. circuit-breaker — after N consecutive transport failures telemetry
     self-disables (no more POST, no more fallback write) for the run;
  2. ring-buffer cap — the fallback db is bounded (never unbounded growth);
  3. 4xx is not retried — a 401 secret-desync fails fast, not 3× backoff;
  4. the fallback default lives under ~/.nos, not world-shared /tmp.
"""
from __future__ import annotations

import os

from tests.callback.conftest import FakePlay, FakePlaybook


def _make_plugin(monkeypatch, tmp_path, threshold=None):
    from callback_plugins import wing_telemetry as gt

    monkeypatch.setenv("NOS_TELEMETRY_ENABLED", "1")
    monkeypatch.setenv("WING_EVENTS_SQLITE_FALLBACK",
                       str(tmp_path / "fallback.db"))
    monkeypatch.setenv("WING_EVENTS_BATCH_SIZE", "1")  # flush every event
    # Hermetic: point the transport at a black-hole port so activation-time
    # emits (retro playbook_start + fallback drain) never touch a real Bone that
    # happens to be running on this box (127.0.0.1:8099 = DEFAULT_URL).
    monkeypatch.setenv("WING_EVENTS_URL", "http://127.0.0.1:9/api/v1/events")
    if threshold is not None:
        monkeypatch.setenv("WING_EVENTS_FAILURE_THRESHOLD", str(threshold))
    plugin = gt.CallbackModule()
    plugin._finalize_activation(None)
    plugin.v2_playbook_on_start(FakePlaybook("main.yml"))
    plugin.v2_playbook_on_play_start(FakePlay("p1"))
    return gt, plugin


def test_circuit_breaker_disables_after_threshold(monkeypatch, tmp_path):
    gt, plugin = _make_plugin(monkeypatch, tmp_path, threshold=5)

    class AlwaysFail:
        def send_batch(self, events):
            raise gt.TransportError("401 invalid signature")

    plugin._http = AlwaysFail()

    # Drive past the threshold.
    for i in range(20):
        plugin._emit("task_ok", task="t%d" % i)

    assert plugin._telemetry_disabled is True
    # Once tripped, the fallback stops growing — it holds at most the events
    # spilled BEFORE the breaker opened (threshold-1), never all 20.
    assert plugin._sqlite.count() < 20
    assert plugin._sqlite.count() <= 5


def test_breaker_half_opens_after_reprobe(monkeypatch, tmp_path):
    """A TRANSIENT outage (Bone starting) must not disable telemetry for the
    whole run: once _reprobe_after_sec elapses the breaker half-opens, and a now-
    healthy sink re-enables it."""
    gt, plugin = _make_plugin(monkeypatch, tmp_path, threshold=3)

    class DownThenUp:
        def __init__(self):
            self.up = False

        def send_batch(self, events):
            if not self.up:
                raise gt.TransportError("Connection reset by peer")

    tr = DownThenUp()
    plugin._http = tr
    plugin._reprobe_after_sec = 60.0

    for i in range(10):                       # trip the breaker while "down"
        plugin._emit("task_ok", task="t%d" % i)
    assert plugin._telemetry_disabled is True

    # Bone comes up; pretend the re-probe window elapsed.
    tr.up = True
    plugin._disabled_at = plugin._disabled_at - 120  # 2 min ago

    plugin._emit("task_ok", task="after")     # → half-open, succeeds, closes
    assert plugin._telemetry_disabled is False
    assert plugin._consecutive_failures == 0


def test_success_resets_the_breaker(monkeypatch, tmp_path):
    gt, plugin = _make_plugin(monkeypatch, tmp_path, threshold=5)

    class FlakyThenOK:
        def __init__(self):
            self.calls = 0

        def send_batch(self, events):
            self.calls += 1
            if self.calls <= 3:
                raise gt.TransportError("temporary 503")

    plugin._http = FlakyThenOK()
    # Start from a known state — activation-time emits are not what we test here.
    plugin._consecutive_failures = 0
    plugin._telemetry_disabled = False
    for i in range(6):
        plugin._emit("task_ok", task="t%d" % i)

    # 3 failures then successes — never reached the threshold of 5.
    assert plugin._telemetry_disabled is False
    assert plugin._consecutive_failures == 0


def test_fallback_ring_buffer_is_bounded(monkeypatch, tmp_path):
    from callback_plugins import wing_telemetry as gt

    fb = gt.SQLiteFallback(str(tmp_path / "ring.db"))
    monkeypatch.setattr(fb, "MAX_ROWS", 50, raising=False)
    for i in range(200):
        fb.enqueue([{"run_id": "r", "ts": "t", "type": "task_ok", "n": i}])
    # Bounded to MAX_ROWS (+ at most the last batch), never all 200.
    assert fb.count() <= 51


def test_4xx_is_not_retried(monkeypatch, tmp_path):
    from callback_plugins import wing_telemetry as gt
    from tests.callback.test_http_transport import FakeRequests, FakeResponse

    fake = FakeRequests([FakeResponse(status_code=401, text="bad sig")])
    tr = gt.HTTPTransport("http://x/events", secret="s", session=fake,
                          max_retries=3)
    try:
        tr.send_batch([{"ts": "t", "run_id": "r", "type": "task_ok"}])
    except gt.TransportError:
        pass
    # A single POST — 401 is a client error, no backoff retries.
    assert len(fake.calls) == 1


def test_5xx_is_retried(monkeypatch):
    from callback_plugins import wing_telemetry as gt
    from tests.callback.test_http_transport import FakeRequests, FakeResponse

    fake = FakeRequests([FakeResponse(status_code=503),
                         FakeResponse(status_code=503),
                         FakeResponse(status_code=503)])
    tr = gt.HTTPTransport("http://x/events", secret="s", session=fake,
                          max_retries=3, backoff_base=0.0)
    try:
        tr.send_batch([{"ts": "t", "run_id": "r", "type": "task_ok"}])
    except gt.TransportError:
        pass
    assert len(fake.calls) == 3  # 5xx is transient — all retries used


def test_secret_reheal_on_401(monkeypatch, tmp_path):
    """Mid-run secret rotation (a blank regenerates the HMAC secret after the
    callback loaded it): a 401 re-reads secrets.yml, rebuilds the transport with
    the fresh secret, and does NOT count toward the circuit-breaker."""
    from callback_plugins import wing_telemetry as gt

    monkeypatch.setenv("NOS_TELEMETRY_ENABLED", "1")
    monkeypatch.setenv("WING_EVENTS_SQLITE_FALLBACK", str(tmp_path / "fb.db"))
    monkeypatch.setenv("WING_EVENTS_BATCH_SIZE", "1")
    monkeypatch.setenv("WING_EVENTS_URL", "http://127.0.0.1:9/api/v1/events")

    plugin = gt.CallbackModule()
    plugin._finalize_activation({"wing_telemetry_enabled": True})
    plugin._consecutive_failures = 0
    plugin._telemetry_disabled = False
    plugin._secret = "STALE-SECRET"

    # secrets.yml now holds the rotated value.
    monkeypatch.setattr(gt, "load_hmac_secret_fallback",
                        lambda *a, **k: "FRESH-SECRET")

    class Auth401:
        def send_batch(self, events):
            raise gt.TransportError("bad status 401: invalid signature")

    plugin._http = Auth401()
    plugin._emit("task_ok", task="a")  # 401 → re-heal

    assert plugin._secret == "FRESH-SECRET"
    assert plugin._consecutive_failures == 0        # not counted as a failure
    assert plugin._telemetry_disabled is False
    assert not isinstance(plugin._http, Auth401)     # transport rebuilt


def test_unrendered_template_playvars_are_rejected(monkeypatch, tmp_path):
    """play.get_vars() returns RAW templates. A literal "{{ … }}" URL/secret
    must NEVER be used — the callback keeps DEFAULT_URL and the secrets.yml
    secret instead of signing/POSTing with a broken literal (live 2026-07-17:
    'Failed to parse: …/{{ bone_port | default(8099) }}/…')."""
    from callback_plugins import wing_telemetry as gt

    monkeypatch.setenv("NOS_TELEMETRY_ENABLED", "1")
    monkeypatch.setenv("WING_EVENTS_SQLITE_FALLBACK",
                       str(tmp_path / "fb.db"))
    monkeypatch.delenv("WING_EVENTS_URL", raising=False)
    monkeypatch.delenv("WING_EVENTS_HMAC_SECRET", raising=False)

    plugin = gt.CallbackModule()
    plugin._finalize_activation({
        "wing_telemetry_enabled": True,
        "wing_events_url": "http://127.0.0.1:{{ bone_port | default(8099) }}/api/v1/events",
        "wing_events_hmac_secret": "{{ wing_events_hmac_secret | default(bone_secret) }}",
    })

    assert "{{" not in plugin._url
    assert plugin._url == gt.CallbackModule.DEFAULT_URL
    assert plugin._secret is None or "{{" not in str(plugin._secret)


def test_default_fallback_path_is_private_sidecar_not_tmp():
    from callback_plugins import wing_telemetry as gt

    assert gt.CallbackModule.DEFAULT_SQLITE.endswith(
        os.path.join(".nos", "events-fallback.db"))
    assert not gt.CallbackModule.DEFAULT_SQLITE.startswith("/tmp")
