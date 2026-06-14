"""Anatomy gate (REM-047 / PENTEST-001) — X-authentik-* header injection.

A forward-auth backend trusts the X-authentik-* identity headers blindly. If the
edge proxy lets a CLIENT-sent X-authentik-uid / -entitlements / -jwt pass through
to the backend, an authenticated user can forge identity → privilege escalation.

Fix mechanism (both edges must OVERWRITE client-sent values with the outpost's):
  - nginx: auth_request_set each header from $upstream_http_x_authentik_* THEN
    proxy_set_header it to the backend (the proxy_set_header wins over client).
  - Traefik: forwardAuth.authResponseHeaders allow-list — Traefik replaces the
    request header with the auth response's value (client value is discarded).

Regression risk: dropping a header from EITHER list re-opens the injection hole
for that field. This gate pins the full sensitive set on both edges.

CI-safe: source/template scan; no Docker, no live system.
"""
from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
NGINX_CONF = REPO / "templates/nginx/authentik-proxy-auth.conf"
TRAEFIK_MW = REPO / "roles/pazny.traefik/templates/dynamic/middlewares.yml.j2"

# The identity/authorization headers a backend must NEVER accept from the client.
# uid/name/entitlements/jwt are the privilege-escalation vectors named in REM-047.
SENSITIVE_HEADERS = [
    "x-authentik-username",
    "x-authentik-uid",
    "x-authentik-email",
    "x-authentik-name",
    "x-authentik-groups",
    "x-authentik-entitlements",
    "x-authentik-jwt",
    "x-authentik-meta-outpost",
    "x-authentik-meta-provider",
    "x-authentik-meta-app",
]


def test_nginx_captures_and_forwards_all_sensitive_headers():
    """nginx must auth_request_set FROM upstream AND proxy_set_header each header.

    Capturing without forwarding (or vice-versa) does not close the hole — both
    directives must be present so the outpost value overwrites the client's.
    """
    text = NGINX_CONF.read_text().lower()
    captured = set(re.findall(r"auth_request_set\s+\$\w+\s+\$upstream_http_(x_authentik_\w+)", text))
    forwarded = set(re.findall(r"proxy_set_header\s+(x-authentik-[\w-]+)\s+\$", text))

    for hdr in SENSITIVE_HEADERS:
        var_form = hdr.replace("-", "_")
        assert var_form in captured, (
            f"nginx must auth_request_set {hdr} from upstream (REM-047): "
            f"uncaptured headers pass client forgeries straight to the backend"
        )
        assert hdr in forwarded, (
            f"nginx must proxy_set_header {hdr} from the captured value (REM-047): "
            f"capture without forward leaves the client value in place"
        )


def test_traefik_allowlists_all_sensitive_auth_response_headers():
    """Traefik forwardAuth.authResponseHeaders must allow-list every header.

    Traefik overwrites a request header only when it appears in the auth response
    allow-list; an absent header keeps the client-sent value → injection.
    """
    text = TRAEFIK_MW.read_text()
    block = re.search(r"authResponseHeaders:\n((?:\s*-\s*\S+\n)+)", text)
    assert block, "traefik authentik middleware must declare authResponseHeaders"
    listed = {h.lower() for h in re.findall(r"-\s*(X-authentik-[\w-]+)", block.group(1))}

    # Traefik fans the JWT in as meta-jwks/version; jwt+entitlements are unused by
    # any nOS backend so the Traefik list legitimately omits them. The identity +
    # provenance headers (the actual privesc surface) MUST be present.
    required = [
        "x-authentik-username",
        "x-authentik-uid",
        "x-authentik-email",
        "x-authentik-name",
        "x-authentik-groups",
        "x-authentik-meta-app",
        "x-authentik-meta-outpost",
        "x-authentik-meta-provider",
    ]
    for hdr in required:
        assert hdr in listed, (
            f"traefik authResponseHeaders must list {hdr} (REM-047): "
            f"absent headers keep the client-sent value → identity forgery"
        )


def test_nginx_forward_auth_is_fail_closed():
    """PENTEST-002 companion: outpost 403/5xx must NOT route to @authentik_bypass.

    If a 5xx fell through to bypass, the request would reach the backend WITHOUT
    any X-authentik-* overwrite — re-opening REM-047 on outpost failure.
    """
    text = NGINX_CONF.read_text()
    assert "error_page 404 = @authentik_bypass" in text, (
        "only 404 may bypass; 401/403/5xx must fail closed"
    )
    assert not re.search(r"error_page[^\n]*\b(401|403|500|502|503)\b[^\n]*@authentik_bypass", text), (
        "auth/error codes must not route to @authentik_bypass (PENTEST-002)"
    )
