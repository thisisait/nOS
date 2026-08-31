"""One OTLP span per Pulse run, and a traceparent for the child to inherit.

WHY PULSE NEEDS THIS AT ALL. Pulse already records its work well — measured
2026-08-31: 29 jobs, 59 207 runs, 99.97% with stdout captured, exit codes,
durations and `actor_action_id` lineage all in `pulse_runs`, queryable in
Grafana through the Wing SQLite datasource. What it had no answer for was
"this job took 40 seconds, where did they go": the job's calls into Bone, Wing
and the cortex produce spans of their own (since 2026-08-31), and nothing tied
them back to the run that caused them.

THE TRACE ID IS THE RUN ID. `run_id` is a uuid4 and is already the estate's
join key — `pulse_runs.run_id == actor_action_id == agent_sessions.uuid ==
events.actor_action_id`, so one SELECT reconstructs scheduler → agent → ledger.
A uuid4 with its dashes stripped is 32 hex characters, which is exactly a W3C
trace id, so Tempo joins that same chain instead of a parallel one. Minting a
fresh trace id here would have given the join a key nothing else could produce.

WHAT A USER'S OWN EXTENSION GETS. `traceparent()` goes into the child's
environment as `TRACEPARENT`, the W3C standard variable every OTel SDK reads on
startup. So a tool someone writes — a nightly Apple Notes digest into KEAP, say
— becomes a CHILD of its job's span with no nOS-specific code at all: if it is
instrumented, its spans nest; if it is not, the job span still records that it
ran and for how long. Either way the KEAP and Bone spans it triggers sit under
the same trace.

ponytail: fourth hand-rolled OTLP emitter in this estate (Wing PHP, Bone
FastAPI, cortex express, here). Deliberate — Pulse ships as its own venv and
cannot import Bone's, so sharing would mean vendoring a package into both to
save ~40 lines. Revisit if a fifth organ appears.
"""

from __future__ import annotations

import json
import os
import secrets
import threading
import urllib.error
import urllib.request

_ENDPOINT = (os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
             or "http://127.0.0.1:4318").rstrip("/")
_ENABLED = os.environ.get("NOS_PULSE_TRACING", "1") != "0"
_TIMEOUT = 0.3


def trace_id_for(run_id: str) -> str:
    """The run's uuid4 as a 128-bit trace id, or a fresh one if it is not one."""
    candidate = run_id.replace("-", "").lower()
    if len(candidate) == 32 and all(c in "0123456789abcdef" for c in candidate):
        return candidate
    return secrets.token_hex(16)


def traceparent(run_id: str, span_id: str) -> str:
    """W3C traceparent for the child process, sampled."""
    return f"00-{trace_id_for(run_id)}-{span_id}-01"


def new_span_id() -> str:
    return secrets.token_hex(8)


def _kv(key: str, value) -> dict:
    if isinstance(value, bool):
        return {"key": key, "value": {"boolValue": value}}
    if isinstance(value, int):
        return {"key": key, "value": {"intValue": str(value)}}
    return {"key": key, "value": {"stringValue": str(value)}}


def _post(payload: dict) -> None:
    """Never raises. Telemetry may not break the job it describes."""
    try:
        req = urllib.request.Request(
            f"{_ENDPOINT}/v1/traces",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=_TIMEOUT).close()
    except (urllib.error.URLError, OSError, ValueError):
        pass


def export_run(*, job_id: str, run_id: str, span_id: str,
               start_nanos: int, end_nanos: int,
               exit_code: int | None, command: str = "") -> None:
    if not _ENABLED:
        return
    attributes = {
        "pulse.job_id": job_id,
        "pulse.run_id": run_id,
        "pulse.command": command,
    }
    if exit_code is not None:
        attributes["pulse.exit_code"] = exit_code
    failed = exit_code is not None and exit_code != 0
    span = {
        "traceId": trace_id_for(run_id),
        "spanId": span_id,
        "name": f"pulse:{job_id}",
        "kind": 3,                                     # SPAN_KIND_CLIENT
        "startTimeUnixNano": str(start_nanos),
        "endTimeUnixNano": str(end_nanos),
        "attributes": [_kv(k, v) for k, v in attributes.items()],
        "status": ({"code": 2, "message": f"exit {exit_code}"} if failed
                   else {"code": 1}),
    }
    payload = {"resourceSpans": [{
        "resource": {"attributes": [_kv("service.name", "nos.pulse"),
                                    _kv("service.namespace", "nos")]},
        "scopeSpans": [{"scope": {"name": "pulse.run"}, "spans": [span]}],
    }]}
    threading.Thread(target=_post, args=(payload,), daemon=True).start()
