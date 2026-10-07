"""Anatomy gate — martin serves the geo schema as vector tiles, behind the atlas gate.

geo-vector-tiles (2026-10-04). GeoLibre fetches tiles from the browser with
fetch/MapLibre defaults (credentials: same-origin), and Authentik forward_auth
is forward_single (a per-host cookie), so a tiles.<tenant> host would 302 every
tile into Authentik's HTML. The tiles therefore ride atlas.<tenant>/tiles: same
origin, same cookie, same tier-3 app — no CORS at all. This gate pins:

  1. the rendered martin config publishes ONLY the declared geo sources, and
     every key exists in martin 1.16.1's own config schema (vendored);
  2. erasure: no tile cache, Cache-Control no-store, the party sources read
     the view over geo.party_site — an erased party is gone from the next tile;
  3. the compose fragment runs the digest pin, publishes no host port, and
     connects as the read-only `martin` role;
  4. the role's SQL grants nothing outside schema geo;
  5. Traefik renders /tiles on the atlas host WITH authentik@file, only when
     install_martin; atlas itself dials its container (not the host gateway);
  6. a smoke row expects the forward_auth 302 for the tile path.
"""
from __future__ import annotations

import json
import sys
import re
from pathlib import Path

import jinja2
import jsonschema
import pytest
import yaml

from test_origin_pull_is_a_second_door import SERVICES, render  # type: ignore

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import nos_identity as ni  # noqa: E402
ROLE = REPO / "roles/pazny.martin"
SCHEMA = json.loads((REPO / "tests/fixtures/martin-1.16.1-config.schema.json").read_text())
DIGEST = "sha256:59902019bf9038926ff0c71174237d6852e64c457830a6349abe7090be8818ca"
SOURCES = {"party_site", "party_site_parcel", "inspire_cp", "inspire_bu"}


def _config() -> dict:
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    return yaml.safe_load(env.from_string((ROLE / "templates/config.yaml.j2").read_text()).render())


def _unknown_keys(doc: dict, props: dict, where: str) -> list[str]:
    return [f"{where}.{k}" for k in doc if k not in props]


def test_config_publishes_only_the_declared_geo_sources():
    cfg = _config()
    jsonschema.validate(cfg, SCHEMA)
    defs = SCHEMA["$defs"]
    bad = _unknown_keys(cfg, SCHEMA["properties"], "")
    bad += _unknown_keys(cfg["postgres"], defs["PostgresConfig"]["properties"], "postgres")
    for sid, t in cfg["postgres"]["tables"].items():
        bad += _unknown_keys(t, defs["TableInfo"]["properties"], f"tables.{sid}")
    assert not bad, f"keys martin 1.16.1 does not know (it would ignore them): {bad}"
    pg = cfg["postgres"]
    assert pg["auto_publish"] is False, "auto-publish would serve every geometry the role can read"
    assert set(pg["tables"]) == SOURCES
    assert {t["schema"] for t in pg["tables"].values()} == {"geo"}
    assert all(t.get("properties") for t in pg["tables"].values()), "list the columns a tile carries"
    assert pg["connection_string"] == "${MARTIN_PG_URL}", "the DSN (password) stays out of the file"
    # martin expands ${VAR} only in a PLAIN scalar; quoted, it parsed the literal (2026-10-04 crash loop)
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    root = yaml.compose(env.from_string((ROLE / "templates/config.yaml.j2").read_text()).render())
    pgnode = next(v for k, v in root.value if k.value == "postgres")
    dsn = next(v for k, v in pgnode.value if k.value == "connection_string")
    assert dsn.style is None, f"connection_string is {dsn.style!r}-quoted: martin will not expand it"
    assert cfg["route_prefix"] == "/tiles" and cfg["cors"] is False


def test_an_erased_party_leaves_no_tile():
    cfg = _config()
    assert cfg["cache"] == "disable", "a tile cache would outlive geo-project-sites --erase-party"
    assert cfg["cache_control"] == "no-store", "nor may a browser or the CDN keep one"
    assert not (cfg.get("endpoints") or {}).get("purge_cache")
    party = {sid: t for sid, t in cfg["postgres"]["tables"].items() if sid.startswith("party_site")}
    assert party and {t["table"] for t in party.values()} == {"party_site_geom"}
    view = re.search(r"VIEW = \"\"\"(.*?)\"\"\"", (REPO / "tools/geo-project-sites.py").read_text(), re.S)[1]
    assert "CREATE OR REPLACE VIEW geo.party_site_geom" in view and "FROM geo.party_site s" in view, (
        "the party sources must read the table the erase DELETEs from")


def _compose() -> dict:
    d = ni.default_config()
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    env.filters["urlencode"] = lambda s: s
    ctx = {"martin_image": d["martin_image"], "martin_version": d["martin_version"],
           "stacks_dir": "/stacks", "stacks_shared_network": "shared_net", "geo_db_name": "geo",
           "nos_derived_secrets": {"martin_db": "PW"}, "postgresql_ssl_enabled": False,
           "martin_mem_limit": "256m", "martin_cpus": "0.5"}
    text = env.from_string((ROLE / "templates/compose.yml.j2").read_text()).render(**ctx)
    return yaml.safe_load(text)["services"]["martin"]


def test_compose_runs_the_pin_unpublished_as_the_readonly_role():
    svc = _compose()
    assert svc["image"] == f"ghcr.io/maplibre/martin:1.16.1@{DIGEST}"
    assert "ports" not in svc, "no host port: the only way in is the gated /tiles lane"
    assert svc["environment"]["MARTIN_PG_URL"] == "postgres://martin:PW@postgresql:5432/geo?sslmode=disable"
    assert "/stacks/iiab/martin:/etc/martin:ro" in svc["volumes"]
    assert svc["command"] == ["--config", "/etc/martin/config.yaml"]
    d = ni.default_config()
    assert d["install_martin"] is False
    reg = yaml.safe_load((REPO / "files/anatomy/secrets/registry.yml").read_text())["credentials"]
    assert reg["martin_db"] == {"service": "martin", "purpose": "db-password"}


def _post_task(name: str) -> dict:
    tasks = yaml.safe_load((REPO / "roles/pazny.postgresql/tasks/post.yml").read_text())
    return next(t for t in tasks if t["name"] == name)


def _grant_sql() -> list[str]:
    cmd = _post_task("[PostgreSQL] Grant the martin role read-only access to schema geo")["ansible.builtin.command"]
    env = jinja2.Environment(undefined=jinja2.ChainableUndefined)
    text = env.from_string(cmd).render(docker_bin="docker", postgresql_root_user="postgres", geo_db_name="geo")
    sql = " ".join(re.findall(r'-c "([^"]*)"', text))
    return [s.strip() for s in sql.split(";") if s.strip()]


ALLOWED = [
    r"GRANT USAGE ON SCHEMA geo TO martin",
    r"GRANT SELECT ON ALL TABLES IN SCHEMA geo TO martin",
    r"ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA geo GRANT SELECT ON TABLES TO martin",
    r"ALTER ROLE martin SET default_transaction_read_only = on",
]


def test_the_martin_role_is_granted_nothing_outside_geo():
    stmts = _grant_sql()
    assert stmts, "no grant SQL rendered"
    stray = [s for s in stmts if not any(re.fullmatch(a, " ".join(s.split())) for a in ALLOWED)]
    assert not stray, f"statements outside the geo-read allow-list: {stray}"
    assert any("GRANT USAGE ON SCHEMA geo" in s for s in stmts)
    # created by the shared user loop: a bare CREATE USER, no attributes
    sync = _post_task("[PostgreSQL] Create or update users (idempotent password sync)")
    assert "nos_derived_secrets.martin_db" in sync["loop"] and "'user': 'martin'" in sync["loop"]
    assert re.search(r"CREATE USER \{\{ item.user \}\} WITH PASSWORD '\{\{ item.pass \}\}';", sync["ansible.builtin.command"])


@pytest.mark.parametrize("martin_on", [True, False])
def test_tiles_ride_the_atlas_gate(martin_on):
    http = yaml.safe_load(render(SERVICES, install_martin=martin_on))["http"]
    assert http["services"]["geolibre"]["loadBalancer"]["servers"] == [{"url": "http://geolibre:80"}], (
        "atlas must dial its container; the host gateway cannot reach a loopback-published port")
    r = http["routers"].get("geolibre-tiles")
    if not martin_on:
        assert r is None and "geolibre-tiles" not in http["services"]
        return
    assert r["rule"] == "Host(`atlas.example.eu`) && PathPrefix(`/tiles`)"
    assert r["middlewares"][0] == "authentik@file", "party-derived tiles are tier 3, never public"
    assert http["services"]["geolibre-tiles"]["loadBalancer"]["servers"] == [{"url": "http://martin:3000"}]


def test_tiles_smoke_as_forward_auth_answers():
    cat = yaml.safe_load((REPO / "state/smoke-catalog.yml").read_text())["smoke_endpoints"]
    row = next((e for e in cat if e["id"] == "martin"), None)
    assert row, "no smoke row for the tile path"
    assert row["url"] == "https://{{ geolibre_domain }}/tiles/catalog"
    assert row["expect"] == [302] and row["expect_strict"] == [302], row
    assert "install_martin" in row["when"] and "install_geolibre" in row["when"]
