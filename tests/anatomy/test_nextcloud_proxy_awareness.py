"""Anatomy CI gate — Nextcloud reverse-proxy awareness.

NC sits behind Traefik AND the ONLYOFFICE/euro-office docserver calls it
internally over the shared docker net. Without trusted_proxies, NC reads the
docker GATEWAY ip as the client for every request, so its brute-force
protection counts the whole fleet as one IP and 429s the operator with "Too
many requests from your network" (live 2026-06-13, first blank with the
connector wired). This pins the trusted_proxies + overwrite-url wiring so it
can't regress.
"""
from __future__ import annotations

import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
POST = (REPO / "roles/pazny.nextcloud/tasks/post.yml").read_text(encoding="utf-8")
DEFAULTS = (REPO / "roles/pazny.nextcloud/defaults/main.yml").read_text(encoding="utf-8")


def test_trusted_proxies_configured():
    assert "config:system:set trusted_proxies" in POST
    assert "nextcloud_trusted_proxies" in POST and "nextcloud_trusted_proxies:" in DEFAULTS
    # Docker private ranges so NC reads X-Forwarded-For, not the gateway.
    assert "172.16.0.0/12" in DEFAULTS


def test_overwrite_urls_point_at_the_public_domain():
    assert "overwrite.cli.url" in POST and "https://{{ nextcloud_domain }}" in POST
    assert "overwritehost" in POST and "overwriteprotocol" in POST
