"""Anatomy gate — the Traefik API is never anonymously reachable (REM-194).

REM-144 closed one leg (no auto-derived host-gateway router). REM-194 found the
second: `api.insecure: true` served the WHOLE API — including
/api/http/middlewares, which reflects the face-edge / wing-edge anti-spoof tokens
verbatim — on the built-in "traefik" entry point (:8080, bound 0.0.0.0 INSIDE the
container). The compose host-port map (127.0.0.1:<dash>:8080) constrained only
HOST callers; the container also sits on infra_net/shared_net/gated_net, so peer
containers read the tokens off `http://infra-traefik-1:8080/` anonymously and
forged Tier-1 identity into the Face BFF (LIVE-confirmed 2026-08-12).

The fix, and what this gate pins:

  1. `api.insecure` is FALSE — the API is off :8080 entirely.
  2. A dedicated `ping` entry point serves /ping on :8080 (harmless liveness),
     and `ping.entryPoint` is pinned to it (so the host healthcheck/smoke keep
     working without re-exposing the API).
  3. If the dashboard route exists at all, it is the api@internal service gated
     by authentik@file — never anonymous, never a host-gateway upstream.

CI-safe: pure template-source scan; no Docker, no live host.
"""
from __future__ import annotations

import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
STATIC = REPO / "roles" / "pazny.traefik" / "templates" / "traefik.yml.j2"
SERVICES = REPO / "roles" / "pazny.traefik" / "templates" / "dynamic" / "services.yml.j2"


def _static() -> str:
    return STATIC.read_text()


def _static_directives() -> str:
    """traefik.yml.j2 with comment lines stripped — so prose that quotes the old
    `insecure: true` disposition can't satisfy or trip the directive scan."""
    lines = []
    for ln in STATIC.read_text().splitlines():
        stripped = ln.lstrip()
        if stripped.startswith("#"):
            continue
        # Drop trailing inline comments too.
        lines.append(ln.split("#", 1)[0] if "#" in ln else ln)
    return "\n".join(lines)


def _services() -> str:
    return SERVICES.read_text()


def test_api_is_not_insecure():
    txt = _static_directives()
    assert "insecure: false" in txt, (
        "traefik.yml.j2 no longer sets `insecure: false` — REM-194 re-opens the "
        "whole API (incl. the edge tokens in /api/http/middlewares) on :8080 to "
        "every peer container the moment insecure is true again."
    )
    assert "insecure: true" not in txt, (
        "traefik.yml.j2 has a live `insecure: true` directive — that is exactly "
        "the REM-194 regression: the API becomes anonymous on container :8080."
    )


def test_ping_has_its_own_entrypoint():
    """/ping must ride a dedicated entry point, not the (now-gone) API one."""
    txt = _static()
    assert "entryPoint: \"ping\"" in txt or "entryPoint: ping" in txt, (
        "ping is no longer pinned to the dedicated `ping` entry point — with "
        "api.insecure false and no ping entry point, the healthcheck/smoke probe "
        "on :8080/ping stops answering and the container never reports healthy."
    )
    # The dedicated entry point must be declared, bound to :8080.
    assert "ping:\n    address: \":8080\"" in txt, (
        "the dedicated `ping` entry point on :8080 vanished from entryPoints — "
        "the host publish 127.0.0.1:<dash>:8080 would then reach nothing."
    )


def test_dashboard_route_is_sso_gated():
    """If the dashboard route is present, it is api@internal behind authentik."""
    txt = _services()
    if "traefik-dashboard:" not in txt:
        # Route dropped entirely (traefik_dashboard_route_enabled=false) — fine,
        # nothing anonymous exists. Nothing to gate.
        return
    # Isolate the router block.
    block = txt.split("traefik-dashboard:", 1)[1].split("\n\n", 1)[0]
    assert "api@internal" in block, (
        "the traefik-dashboard router no longer points at the built-in "
        "api@internal service — a host-gateway upstream here is REM-144's shape."
    )
    assert "authentik@file" in block, (
        "the traefik-dashboard router lost its authentik@file middleware — the "
        "dashboard/API would be anonymous at the edge again (REM-194/REM-144)."
    )
