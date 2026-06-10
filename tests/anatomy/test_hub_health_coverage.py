"""W6.4 gates (2026-06-10) — Hub health coverage for URL-less backends.

21/57 Hub systems sat "unchecked" forever: backend services (Prometheus,
Loki, MariaDB, …) have no public url so probeAll skipped them, stack-parent
rows have no URL by nature, and DB-class services aren't HTTP at all. Pins:
  - systems.health_url column (probe target ≠ card link) in schema + ALTER
    sweep + ingest mapping + upsert whitelist
  - tcp:// probe scheme for DB-class liveness
  - probeAll prefers health_url and aggregates stack-parent health
  - the registry template ships loopback health_url for Tier-2 backends
"""
from __future__ import annotations

import json
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]

SYSTEM_REPO = REPO / "files/anatomy/wing/app/Model/SystemRepository.php"
INIT_DB = REPO / "files/anatomy/wing/bin/init-db.php"
REGISTRY_TPL = REPO / "templates/service-registry.json.j2"


def test_health_url_column_in_schema_and_alter_sweep():
    src = INIT_DB.read_text()
    assert "health_url      TEXT" in src, "fresh-create lost health_url"
    # Existing DBs must pick the column up via the idempotent sweep.
    sweep = src[src.index("addMissingColumns($db, 'systems'"):]
    assert "'health_url' => 'TEXT'" in sweep[:200]


def test_health_url_ingested_and_whitelisted():
    src = SYSTEM_REPO.read_text()
    assert "'health_url' => $svc['health_url'] ?? null" in src, (
        "ingestRegistry no longer maps health_url from the registry JSON"
    )
    wl = src[src.index("WRITABLE_FIELDS"):]
    wl = wl[:wl.index("];")]
    assert "'health_url'" in wl, (
        "upsert whitelist (SEC-7) dropped health_url — ingest would "
        "silently discard it"
    )


def test_probe_supports_tcp_scheme():
    src = SYSTEM_REPO.read_text()
    body = src[src.index("function probe("):]
    assert "str_starts_with($url, 'tcp://')" in body[:600]
    tcp = src[src.index("function probeTcp"):]
    assert "fsockopen" in tcp[:800]


def test_probe_all_prefers_health_url_and_aggregates_stacks():
    src = SYSTEM_REPO.read_text()
    body = src[src.index("function probeAll"):]
    assert "health_url" in body[:900], "probeAll no longer reads health_url"
    assert "aggregateStackHealth" in body[:1400], (
        "stack-parent aggregation dropped — 9 stack rows would return to "
        "eternal 'unchecked'"
    )
    agg = src[src.index("function aggregateStackHealth"):]
    # down if ANY checked child down; up if ALL checked children up.
    assert "$down > 0 ? 'down'" in agg


def test_registry_template_ships_backend_health_urls():
    src = REGISTRY_TPL.read_text()
    # Spot-pin the four classes: HTTP health endpoint, /metrics exporter,
    # tcp:// DB, and a plain HTTP UI.
    assert '"/-/healthy"' in src, "Prometheus health_url lost"
    assert '"http://127.0.0.1:9113/metrics"' in src, "exporter health_url lost"
    assert 'tcp://127.0.0.1:" ~ (mariadb_port' in src, "MariaDB tcp probe lost"
    assert 'uptime_kuma_port | default(3001))' in src
    # Count stays honest: at least 15 backends carry a probe target.
    assert src.count('"health_url"') >= 15, (
        f"only {src.count('\"health_url\"')} health_url entries left in the "
        "registry template (expected >= 15)"
    )
