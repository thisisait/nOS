"""OTLP/HTTP trace export for Bone — one span per request, no SDK.

WHY HAND-ROLLED. `App\\AgentKit\\Telemetry\\OtelExporter` has been speaking
OTLP/HTTP JSON to Alloy on 4318 in 94 lines of PHP since AgentKit shipped, and
this is the same payload one service along. The alternative,
`opentelemetry-instrumentation-fastapi`, brings the API, SDK, exporter and
instrumentation packages plus their transitive deps into an organ whose entire
requirement is "POST a JSON object per request".

WHAT IT IS FOR. Measured 2026-08-31: Tempo held 950 traces and every one was an
AgentKit `agent.session`. Bone is the estate's HTTP bridge — the loop, the
weakness readers and the agents all go through it — and it was invisible, so
"why was that call slow" had no answer an agent could reach through
grafana-mcp.

ponytail: fire-and-forget POST per request with a 300ms cap, handed to a daemon
thread so the response never waits on the collector. A batching processor would
be more moving parts than this estate's request volume justifies; revisit if
thread-per-request ever shows up in latency.

NOT INSTRUMENTED: an inbound `traceparent` header is ignored — every span here
starts a NEW trace. `export_span` takes `trace_id`/`span_id` so a caller can
continue one, and nothing passes them today. A Pulse job that calls Bone
therefore does NOT appear under its run's trace.
"""

from __future__ import annotations

import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.request

_ENDPOINT = (os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
             or "http://127.0.0.1:4318").rstrip("/")
_SERVICE = os.environ.get("OTEL_SERVICE_NAME", "nos.bone")
_ENABLED = os.environ.get("NOS_BONE_TRACING", "1") != "0"
_TIMEOUT = 0.3


def _kv(key: str, value) -> dict:
    if isinstance(value, bool):
        return {"key": key, "value": {"boolValue": value}}
    if isinstance(value, int):
        return {"key": key, "value": {"intValue": str(value)}}
    return {"key": key, "value": {"stringValue": str(value)}}


def _post(payload: dict) -> None:
    """Never raises. Telemetry may not break the response it describes."""
    try:
        req = urllib.request.Request(
            f"{_ENDPOINT}/v1/traces",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=_TIMEOUT).close()
    except (urllib.error.URLError, OSError, ValueError):
        pass


def export_span(*, name: str, start_ns: int, end_ns: int,
                attributes: dict, error: str | None = None,
                trace_id: str | None = None, span_id: str | None = None) -> None:
    if not _ENABLED:
        return
    span = {
        "traceId": trace_id or secrets.token_hex(16),
        "spanId": span_id or secrets.token_hex(8),
        "name": name,
        "kind": 2,                                    # SPAN_KIND_SERVER
        "startTimeUnixNano": str(start_ns),
        "endTimeUnixNano": str(end_ns),
        "attributes": [_kv(k, v) for k, v in attributes.items()],
        "status": {"code": 2, "message": error} if error else {"code": 1},
    }
    payload = {"resourceSpans": [{
        "resource": {"attributes": [_kv("service.name", _SERVICE),
                                    _kv("service.namespace", "nos")]},
        "scopeSpans": [{"scope": {"name": "bone.http"}, "spans": [span]}],
    }]}
    # Off the response path: the caller should not wait on the collector.
    # The try is not decoration: `Thread.start()` raises RuntimeError when the
    # process is out of threads or already shutting down, and this call sits in
    # the middleware's `finally` — a raise there REPLACES the exception the
    # request was already propagating. Telemetry may not break the response.
    try:
        threading.Thread(target=_post, args=(payload,), daemon=True).start()
    except RuntimeError:
        pass


def install(app) -> None:
    """One span per request, for every route the app has or will have."""
    if not _ENABLED:
        return

    @app.middleware("http")
    async def _trace(request, call_next):                    # noqa: ANN001
        start = time.time_ns()
        error = None
        try:
            response = await call_next(request)
            status = response.status_code
        except Exception as exc:                              # noqa: BLE001
            status, error = 500, f"{type(exc).__name__}: {exc}"
            raise
        finally:
            export_span(
                name=f"{request.method} {request.url.path}",
                start_ns=start, end_ns=time.time_ns(),
                attributes={
                    "http.request.method": request.method,
                    "url.path": request.url.path,
                    "http.response.status_code": status,
                },
                # `or`, not a conditional: a route that RETURNS 500 raises
                # nothing, so `error` is None and the old
                # `error if (error or status >= 500) else None` collapsed to
                # plain `error` — the 5xx branch could never set one, and the
                # span went to Tempo with status Ok. cortex/otel.ts and Wing's
                # BasePresenter both mark a returned 5xx; this now agrees.
                error=error or (f"HTTP {status}" if status >= 500 else None),
            )
        return response
