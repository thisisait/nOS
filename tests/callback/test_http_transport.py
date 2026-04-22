"""HTTPTransport: retry, backoff, HMAC header, batch serialisation."""
from __future__ import annotations

import json

import pytest


class FakeResponse:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text


class FakeRequests:
    """Minimal stand-in for ``requests``."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def post(self, url, data=None, headers=None, timeout=None):
        self.calls.append(
            {"url": url, "data": data, "headers": headers,
             "timeout": timeout})
        if not self._responses:
            raise RuntimeError("FakeRequests exhausted")
        r = self._responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def test_successful_post_sends_hmac_header(monkeypatch):
    from callback_plugins import glasswing_telemetry as gt

    fake = FakeRequests([FakeResponse(202)])
    tr = gt.HTTPTransport(url="http://example/api/v1/events",
                          secret="topsecret",
                          session=fake, max_retries=3, backoff_base=0.0)
    tr.send_batch([{"type": "task_ok", "run_id": "run_x", "ts": "now"}])

    assert len(fake.calls) == 1
    headers = fake.calls[0]["headers"]
    assert "X-Glasswing-Signature" in headers
    assert headers["X-Glasswing-Signature"].startswith("sha256=")
    # Body is valid JSON with events array
    body = json.loads(fake.calls[0]["data"].decode("utf-8"))
    assert "events" in body and len(body["events"]) == 1


def test_no_hmac_header_when_secret_missing(monkeypatch):
    from callback_plugins import glasswing_telemetry as gt

    fake = FakeRequests([FakeResponse(202)])
    tr = gt.HTTPTransport(url="http://example/api/v1/events",
                          secret=None,
                          session=fake, max_retries=1, backoff_base=0.0)
    tr.send_batch([{"type": "task_ok", "run_id": "run_x", "ts": "now"}])

    assert "X-Glasswing-Signature" not in fake.calls[0]["headers"]


def test_retries_then_succeeds(monkeypatch):
    from callback_plugins import glasswing_telemetry as gt

    fake = FakeRequests([
        ConnectionError("net down"),
        FakeResponse(500, "oops"),
        FakeResponse(200),
    ])
    tr = gt.HTTPTransport(url="http://example/api/v1/events",
                          secret="s",
                          session=fake, max_retries=3, backoff_base=0.0)
    tr.send_batch([{"type": "task_ok", "run_id": "run_x", "ts": "now"}])
    assert len(fake.calls) == 3


def test_raises_after_all_retries_fail():
    from callback_plugins import glasswing_telemetry as gt

    fake = FakeRequests([
        ConnectionError("x"),
        ConnectionError("y"),
        ConnectionError("z"),
    ])
    tr = gt.HTTPTransport(url="http://example/api/v1/events",
                          secret="s",
                          session=fake, max_retries=3, backoff_base=0.0)
    with pytest.raises(gt.TransportError):
        tr.send_batch([{"type": "task_ok", "run_id": "run_x", "ts": "now"}])
    assert len(fake.calls) == 3


def test_non_2xx_status_triggers_retry():
    from callback_plugins import glasswing_telemetry as gt

    fake = FakeRequests([
        FakeResponse(500, "fail"),
        FakeResponse(502, "bad gateway"),
        FakeResponse(503, "timeout"),
    ])
    tr = gt.HTTPTransport(url="http://example/api/v1/events",
                          secret="s",
                          session=fake, max_retries=3, backoff_base=0.0)
    with pytest.raises(gt.TransportError):
        tr.send_batch([{"type": "task_ok", "run_id": "run_x", "ts": "now"}])
    assert len(fake.calls) == 3


def test_empty_batch_is_noop():
    from callback_plugins import glasswing_telemetry as gt

    fake = FakeRequests([])
    tr = gt.HTTPTransport(url="http://example/api/v1/events",
                          secret="s", session=fake)
    tr.send_batch([])  # should not raise, should not call requests
    assert fake.calls == []


def test_hmac_signature_stable():
    from callback_plugins import glasswing_telemetry as gt

    body = b'{"events":[{"ts":"2026-01-01T00:00:00Z"}]}'
    sig1 = gt.hmac_signature("secret", body)
    sig2 = gt.hmac_signature("secret", body)
    assert sig1 == sig2
    assert sig1.startswith("sha256=")
    # Different secret -> different signature
    assert gt.hmac_signature("other", body) != sig1
