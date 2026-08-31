"""A Pulse run emits a span, and hands the child a traceparent to inherit.

WHY THIS IS THE EXTENSION CONTRACT. nOS expects operators to bring their own
work — a nightly digest of Apple Notes into KEAP is the shape: a CLI tool plus
a Pulse job. Everything else that tool needs is already there — `pulse_runs`
records exit code, duration, stdout tail and `actor_action_id` for 59 207 runs
(measured 2026-08-31), Grafana reads that table through the Wing SQLite
datasource, and A9 notifies on failure.

The one thing missing was the trace. The estate's three organs emit spans as of
2026-08-31, so a job that calls Bone or the cortex produced spans that nothing
tied back to the run that caused them. `TRACEPARENT` closes it in the standard
way: it is the W3C variable every OTel SDK reads at startup, so an extension
nests under its job with NO nOS-specific code, and one that is not instrumented
at all still gets a span saying it ran and for how long.

TWO PROPERTIES, both easy to break silently:

1. The trace id must BE the run id. Every other store in the estate joins on
   `run_id`; a freshly minted trace id would put Tempo on a key nothing else
   can produce, and the join would look present while resolving to nothing.
2. `setdefault`, never assignment. A job that sets its own trace context — one
   continuing a trace started elsewhere — must keep it, exactly as
   `PULSE_RUN_ID` already works.
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "files/anatomy/pulse"))

from pulse import otel  # noqa: E402

DAEMON = ROOT / "files/anatomy/pulse/pulse/daemon.py"


def test_the_trace_id_is_the_run_id() -> None:
    run_id = "550e8400-e29b-41d4-a716-446655440000"
    assert otel.trace_id_for(run_id) == "550e8400e29b41d4a716446655440000", (
        "the trace id is no longer derived from run_id — Tempo would join on a "
        "key that pulse_runs, events and agent_sessions cannot produce")


def test_a_non_uuid_run_id_still_yields_a_valid_trace_id() -> None:
    """Never emit a malformed id: Tempo drops the span and the run is invisible."""
    for odd in ("", "manual-1234", "not-a-uuid", "ZZZZ" * 8):
        got = otel.trace_id_for(odd)
        assert len(got) == 32 and all(c in "0123456789abcdef" for c in got), (
            f"trace_id_for({odd!r}) returned {got!r}, which Tempo will reject")


def test_the_traceparent_is_w3c_and_sampled() -> None:
    tp = otel.traceparent("550e8400-e29b-41d4-a716-446655440000", "abcdef0123456789")
    parts = tp.split("-")
    assert len(parts) == 4 and parts[0] == "00", f"not a W3C traceparent: {tp}"
    assert len(parts[1]) == 32 and len(parts[2]) == 16, f"bad id lengths: {tp}"
    assert parts[3] == "01", (
        "the traceparent is marked NOT sampled — a child SDK reading it would "
        "correctly drop every span it makes")


def test_the_daemon_hands_it_to_the_child_without_overwriting() -> None:
    body = DAEMON.read_text(encoding="utf-8")
    assert 'env.setdefault("TRACEPARENT"' in body, (
        "the daemon does not put TRACEPARENT in the child's environment — a "
        "user's own tool has no way to nest under its job's span")
    assert 'env["TRACEPARENT"]' not in body, (
        "TRACEPARENT is assigned rather than setdefault — a job continuing a "
        "trace from elsewhere would have its context silently replaced")


def test_the_daemon_actually_exports_the_span() -> None:
    body = DAEMON.read_text(encoding="utf-8")
    assert "otel.export_run(" in body, (
        "the daemon builds a traceparent but exports no span of its own, so "
        "the child's spans would have a parent that does not exist")


def test_a_failed_run_is_an_error_span() -> None:
    """A green span for a failed job is worse than no span: it reads as fine."""
    sent = {}
    original = otel._post
    otel._post = lambda payload: sent.update(payload)
    try:
        otel.export_run(job_id="j", run_id="550e8400-e29b-41d4-a716-446655440000",
                        span_id="abcdef0123456789", start_nanos=1, end_nanos=2,
                        exit_code=1)
        # export_run posts on a thread; join it rather than sleeping.
        import threading
        for t in threading.enumerate():
            if t is not threading.current_thread() and t.daemon:
                t.join(timeout=2)
    finally:
        otel._post = original
    span = sent["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    assert span["status"]["code"] == 2, (
        f"exit_code=1 produced status {span['status']} — a failed job would "
        "show green in Tempo")


def test_the_env_scoping_does_not_swallow_it() -> None:
    """Setting TRACEPARENT is not the same as the child RECEIVING it.

    Two allow-lists sit between a declared field and a running job — the Pulse
    catalog's token table and, here, `_safe_env`, which strips secrets from the
    inherited environment and refuses loader/PATH overrides (`DYLD_*`, `LD_*`,
    `PYTHONPATH`). This estate has twice shipped a field that a later filter
    dropped in silence, and a dropped TRACEPARENT looks exactly like a child
    that simply was not instrumented — the job span still appears, the child
    spans just never nest, and nobody can tell which of the two happened.
    """
    from pulse.runners.subprocess import _safe_env

    tp = otel.traceparent("550e8400-e29b-41d4-a716-446655440000", "abcdef0123456789")
    env = _safe_env({"TRACEPARENT": tp, "PULSE_RUN_ID": "x"})
    assert env.get("TRACEPARENT") == tp, (
        "_safe_env dropped or rewrote TRACEPARENT, so the child inherits no "
        "trace context and its spans land in a trace of their own")
