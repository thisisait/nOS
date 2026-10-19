"""A visitor who types the host's IP lands on the face, not a 404.

Traefik routes by name; http(s)://<host ip> answered 404 on spark1
(2026-10-19), the first address a LAN visitor tries. The bare-IP routers
redirect to face_domain, one per entrypoint (a router with tls matches only
TLS), and the web entrypoint's blanket https redirect sits BELOW them by
priority, so http://<ip> is not sent into a certificate warning first.
"""
from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
T = REPO / "roles" / "pazny.traefik" / "templates"


def test_both_entrypoints_route_a_bare_ip_to_the_face():
    svc = (T / "dynamic" / "services.yml.j2").read_text()
    assert "bare-ip-to-face-{{ _ep }}" in svc and "('web', none), ('websecure', {})" in svc
    assert "HostRegexp(`^[0-9]+" in svc
    mw = (T / "dynamic" / "middlewares.yml.j2").read_text()
    assert re.search(r'bare-ip-to-face:\s*\n\s*redirectRegex:', mw)
    assert "https://{{ face_domain" in mw


def test_the_blanket_https_redirect_yields_to_it():
    static = (T / "traefik.yml.j2").read_text()
    m = re.search(r"redirections:.*?priority:\s*(\d+)", static, re.S)
    svc = (T / "dynamic" / "services.yml.j2").read_text()
    p = re.search(r"bare-ip-to-face-.*?priority:\s*(\d+)", svc, re.S)
    assert m and p and int(m.group(1)) < int(p.group(1))
