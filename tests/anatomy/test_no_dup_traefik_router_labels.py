"""Anatomy gate — plugin compose-extensions must not emit Traefik ROUTER labels.

nOS Tier-1 services are routed by the Traefik FILE provider (state/manifest.yml →
services.yml), which sets the correct INTERNAL container port AND the per-mode
forward-auth middleware (authentik@file for forward_auth/header_oidc; none for a
native_oidc/JWT backend like OnlyOffice). When a plugin compose-extension ALSO
emits docker-provider router labels (`traefik.http.routers.*`), Traefik builds a
SECOND router for the same Host at the SAME priority — a tie that resolves
non-deterministically per reload. The label-derived router used a host-published
port var (kiwix 8888≠8080, ntfy 2586≠80, keap 8091≠8080, …), so when it won the
coin-flip the proxy 502'd (live root-cause of the Jellyfin/Calibre/Kiwix 502s,
2026-06-02). It could also silently add/drop forward-auth vs the file router.

Fix + invariant: plugin compose-extensions wire services into middleware via the
FILE provider only; they MUST NOT declare `traefik.http.routers.*` /
`traefik.http.services.*` router/service labels. `traefik.enable=false` (docker
provider opt-out) is allowed.

CI-safe: source scan; no Docker.
"""
from __future__ import annotations

import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
PLUGINS = REPO / "files" / "anatomy" / "plugins"

FORBIDDEN = ("traefik.http.routers.", "traefik.http.services.")


def _compose_exts() -> list[pathlib.Path]:
    return sorted(PLUGINS.glob("*/templates/*.compose.yml.j2"))


def test_compose_exts_exist():
    assert _compose_exts(), "no plugin compose-extensions found — glob/path drift?"


def test_no_docker_provider_router_labels():
    offenders = []
    for f in _compose_exts():
        text = f.read_text()
        for needle in FORBIDDEN:
            if needle in text:
                offenders.append(f"{f.relative_to(REPO)} :: {needle}")
    assert not offenders, (
        "plugin compose-extensions must not emit docker-provider router/service labels "
        "(Tier-1 services are file-provider-routed; a second @docker router collides with "
        "@file and 502s on coin-flip). Offenders:\n  " + "\n  ".join(offenders)
    )
