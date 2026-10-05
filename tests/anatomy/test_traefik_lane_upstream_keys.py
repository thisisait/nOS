"""Anatomy gate — a machine lane may name its own upstream, strip its prefix, and allow exact paths.

nos-forum (2026-10-03): the browser's SpacetimeDB WebSocket rides `forum.<tld>/stdb/…`
to `spacetimedb:3000`, not to forum-web. Before these keys a lane could only reuse its
row's upstream, so `/stdb` would have reached forum-web (wrong service) and, as a plain
PathPrefix, the whole SpacetimeDB HTTP API (publish, sql) would have been one typo away.
Pins: the lane's own service URL, the stripPrefix middleware, and Path-only matching.
Render harness: tests/anatomy/test_origin_pull_is_a_second_door.py.
"""

from __future__ import annotations

import yaml

from test_origin_pull_is_a_second_door import SERVICES, render  # type: ignore


def _doc(**over) -> dict:
    return yaml.safe_load(render(SERVICES, **over))["http"]


def test_stdb_lane_routes_to_spacetimedb_with_strip_and_exact_paths():
    http = _doc()
    r = http["routers"]["nos-forum-stdb"]
    assert r["service"] == "nos-forum-stdb"
    assert "PathPrefix" not in r["rule"], "a prefix lane would open the whole SpacetimeDB API"
    assert "Path(`/stdb/v1/identity/websocket-token`)" in r["rule"]
    assert "Path(`/stdb/v1/database/nos-forum/subscribe`)" in r["rule"]
    assert r["middlewares"][0] == "nos-forum-stdb-strip"
    assert "authentik@file" not in r["middlewares"]
    assert http["services"]["nos-forum-stdb"]["loadBalancer"]["servers"] == [{"url": "http://spacetimedb:3000"}]
    assert http["middlewares"]["nos-forum-stdb-strip"] == {"stripPrefix": {"prefixes": ["/stdb"]}}
    # the main router is native OIDC: no forward-auth, upstream forum-web
    assert "authentik@file" not in http["routers"]["nos-forum"]["middlewares"]
    assert http["services"]["nos-forum"]["loadBalancer"]["servers"] == [{"url": "http://nos-forum:5091"}]


def test_plain_lanes_are_unchanged():
    keap = _doc()["routers"]["keap-agent"]
    assert keap["service"] == "keap" and "PathPrefix(`/agent/v1`)" in keap["rule"]
    assert keap["middlewares"] == ["security-headers@file", "compress@file"]


def test_red_without_the_keys():
    lanes = {"nos_forum": [{"name": "stdb", "prefixes": ["/stdb"]}]}
    r = _doc(traefik_machine_lanes=lanes)["routers"]["nos-forum-stdb"]
    assert r["service"] == "nos-forum" and "PathPrefix(`/stdb`)" in r["rule"]


def test_forum_off_renders_no_forum_router():
    http = _doc(install_nos_forum=False)
    assert "nos-forum-stdb" not in http["routers"] and "nos-forum-stdb" not in http["services"]


def test_stdb_lane_keeps_its_token_out_of_the_access_log():
    # The subscribe URL carries ?token=<60 s SpacetimeDB JWT with email/groups>; Traefik's
    # JSON access log records RequestPath with the query (200 rows in Loki, 2026-10-03).
    routers = _doc(traefik_origin_pull_enabled=True)["routers"]
    for name in ("nos-forum-stdb", "nos-forum-stdb-origin"):
        assert routers[name].get("observability", {}).get("accessLogs") is False, name
    assert "observability" not in routers["keap-agent"], "the opt-out stays scoped to the lane"
