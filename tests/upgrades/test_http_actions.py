"""http.wait and http.get_all — using the injected transport fixtures."""

from __future__ import absolute_import, division, print_function

import os

from module_utils.nos_upgrade_actions import http_ops as ho


def test_http_wait_returns_on_expected_status(base_ctx, fake_http):
    fake_http.responses = [(503, b"not yet"), (200, b"ok")]
    base_ctx["http_request"] = fake_http
    res = ho.handle_http_wait(
        {"url": "https://svc.dev.local/health", "expect_status": 200,
         "timeout_sec": 30, "interval_sec": 1},
        base_ctx,
    )
    assert res["success"]
    assert res["result"]["attempts"] == 2
    assert len(fake_http.calls) == 2


def test_http_wait_times_out(base_ctx, fake_http):
    fake_http.responses = [(503, b"")] * 10
    base_ctx["http_request"] = fake_http
    # Use an internal clock trick: sleep fixture is a no-op so timeout_sec=0
    # would make the loop exit on entry. Use negative to force immediate fail.
    base_ctx["sleep"] = lambda _s: None

    import time
    # Freeze "time" so the deadline check fires after N iterations.
    real_time = time.time
    clock = {"t": 1000.0}

    def _tick():
        clock["t"] += 2.0
        return clock["t"]

    time.time = _tick
    try:
        res = ho.handle_http_wait(
            {"url": "https://svc.dev.local/h", "expect_status": 200,
             "timeout_sec": 3, "interval_sec": 1},
            base_ctx,
        )
    finally:
        time.time = real_time
    assert not res["success"]
    assert "timeout" in res["error"]


def test_http_wait_tcp_scheme(base_ctx, fake_tcp):
    fake_tcp.sequence = [False, True]
    base_ctx["tcp_probe"] = fake_tcp
    res = ho.handle_http_wait(
        {"url": "tcp://localhost:5432", "timeout_sec": 10, "interval_sec": 1},
        base_ctx,
    )
    assert res["success"]
    assert res["result"]["mode"] == "tcp"
    assert res["result"]["attempts"] == 2


def test_http_get_all_writes_body(tmp_path, base_ctx, fake_http):
    fake_http.responses = [(200, b'{"dashboards":[]}')]
    base_ctx["http_request"] = fake_http
    save = tmp_path / "out" / "dash.json"
    res = ho.handle_http_get_all(
        {"url": "https://g.dev.local/api/search", "save_to": str(save)},
        base_ctx,
    )
    assert res["success"]
    assert save.read_bytes() == b'{"dashboards":[]}'


def test_http_get_all_bearer_token_from_vars(tmp_path, base_ctx, fake_http):
    fake_http.responses = [(200, b"{}")]
    base_ctx["http_request"] = fake_http
    base_ctx["vars"] = {"grafana_admin_api_token": "s3cret"}
    save = tmp_path / "dash.json"
    ho.handle_http_get_all({
        "url": "https://g/api",
        "save_to": str(save),
        "auth": {"type": "bearer", "token_var": "grafana_admin_api_token"},
    }, base_ctx)
    assert fake_http.calls[0]["headers"].get("Authorization") == "Bearer s3cret"


def test_http_get_all_non_2xx_strict(tmp_path, base_ctx, fake_http):
    fake_http.responses = [(500, b"oops")]
    base_ctx["http_request"] = fake_http
    save = tmp_path / "f.json"
    res = ho.handle_http_get_all(
        {"url": "https://x", "save_to": str(save)},
        base_ctx,
    )
    assert not res["success"]


def test_http_get_all_ignore_errors(tmp_path, base_ctx, fake_http):
    fake_http.responses = [(500, b"oops")]
    base_ctx["http_request"] = fake_http
    save = tmp_path / "f.json"
    res = ho.handle_http_get_all(
        {"url": "https://x", "save_to": str(save), "ignore_errors": True},
        base_ctx,
    )
    assert res["success"]
    assert not res["changed"]
    assert res["result"]["ok"] is False
