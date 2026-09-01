"""Anatomy CI gate — the Grafana Logs→Traces link needs something emitting trace_id.

The Loki datasource declares a derived field that turns a `trace_id` in a log
line into a click-through to Tempo:

    matcherRegex: '"trace_id":"(\\w+)"'
    datasourceUid: tempo

Until 2026-08-31 that link COULD NOT FIRE. Nothing in the estate wrote a
trace_id into a log line — a Loki range query over 24h and 346 026 lines
returned zero matches. The datasource provisioned cleanly, Grafana rendered the
field, and the button was decoration. Absence is not success.

Traefik with `tracing:` on is the producer: its JSON access log carries a
lowercase `trace_id` per request, and that id resolves in Tempo (verified live
2026-09-01, Loki line → `GET /api/traces/<id>` → 200).

So the link rests on THREE artifacts agreeing, and this gate pins the two that
a future edit can silently break:

  1. Traefik's accessLog is `json` — the plain CLF format has no trace_id.
  2. Traefik's `tracing:` block exists — without it the field is empty.

What the gate cannot see is whether Tempo is reachable at run time; that is
`--tags verify`'s job, not pytest's.
"""

from __future__ import annotations

import pathlib
import re

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
TRAEFIK_TPL = REPO / "roles" / "pazny.traefik" / "templates" / "traefik.yml.j2"
LOKI_DS = (
    REPO / "files" / "anatomy" / "plugins" / "grafana-loki"
    / "provisioning" / "datasources" / "loki.yml.j2"
)


def _strip_jinja(text: str) -> str:
    """Comments out, expressions replaced by a scalar so the YAML parses."""
    text = re.sub(r"\{#.*?#\}", "", text, flags=re.S)
    text = re.sub(r"\{%.*?%\}", "", text, flags=re.S)
    return re.sub(r"\{\{.*?\}\}", "x", text, flags=re.S)


def _traefik() -> dict:
    return yaml.safe_load(_strip_jinja(TRAEFIK_TPL.read_text()))


def test_the_derived_field_is_still_declared():
    """If this disappears the rest of the gate is guarding nothing — fail loudly
    rather than pass vacuously."""
    ds = yaml.safe_load(_strip_jinja(LOKI_DS.read_text()))
    loki = next(d for d in ds["datasources"] if d.get("type") == "loki")
    fields = loki.get("jsonData", {}).get("derivedFields") or []
    assert fields, f"{LOKI_DS.name}: no derivedFields — Logs→Traces link is gone"
    assert any(f.get("datasourceUid") == "tempo" for f in fields), (
        f"{LOKI_DS.name}: no derived field targets the tempo datasource"
    )


def test_traefik_emits_a_trace_id_a_log_line_can_carry():
    cfg = _traefik()

    access = cfg.get("accessLog")
    assert access is not None, "traefik.yml.j2: accessLog block is gone"
    assert access.get("format") == "json", (
        "traefik.yml.j2: accessLog format is not json — the CLF format carries "
        "no trace_id, so the Grafana Logs→Traces link stops firing"
    )

    tracing = cfg.get("tracing")
    assert tracing, (
        "traefik.yml.j2: tracing block is gone — the access log's trace_id field "
        "renders empty and the Logs→Traces link becomes decoration again"
    )
    assert tracing.get("otlp"), "traefik.yml.j2: tracing has no otlp exporter"


def test_the_regex_matches_what_traefik_actually_writes():
    """Shaped after a line captured from `docker logs infra-traefik-1` on
    2026-09-01, trimmed to the fields that matter. The id is minted here rather
    than copied: what the regex has to get right is the key SPELLING — Traefik
    writes both `TraceId` and a lowercase `trace_id`, and the derived field
    matches only the latter — not one particular hex string. (A pasted 32-hex
    literal is also indistinguishable from a credential to
    `test_a_fixture_is_never_a_real_secret`, and correctly trips it.)"""
    import random

    rng = random.Random(20260901)
    tid = "".join(rng.choice("0123456789abcdef") for _ in range(32))
    sample = (
        '{"DownstreamStatus":302,"RouterName":"metabase@file",'
        f'"SpanId":"b1d5a7b32685062f","TraceId":"{tid}","level":"info",'
        f'"span_id":"b1d5a7b32685062f","trace_id":"{tid}"}}'
    )
    ds = yaml.safe_load(_strip_jinja(LOKI_DS.read_text()))
    loki = next(d for d in ds["datasources"] if d.get("type") == "loki")
    field = next(
        f for f in loki["jsonData"]["derivedFields"] if f.get("datasourceUid") == "tempo"
    )
    m = re.search(field["matcherRegex"], sample)
    assert m, (
        f"matcherRegex {field['matcherRegex']!r} does not match a real Traefik "
        f"access-log line — the Logs→Traces link cannot fire"
    )
    assert m.group(1) == tid
