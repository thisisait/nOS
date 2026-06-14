"""Anatomy gate (REM-048 / PENTEST-002) — nginx proxy-auth fail-closed.

When the Authentik outpost is down/unreachable it returns a 5xx. The original
nginx forward-auth config mapped error_page 403 404 500 502 503 → @authentik_bypass
(return 200), so an outpost outage silently GRANTED unauthenticated access to all
13 proxy-auth-protected services. The fix is fail-closed: only a legitimate 404
(path-not-found, e.g. a static asset under /outpost.goauthentik.io) may bypass;
every 5xx routes to @authentik_fail_closed which returns 503 (deny).

REM-047's gate (test_rem047_authentik_header_injection.py) pins the *auth.conf*
side. This gate pins the companion *locations.conf* side — the
/outpost.goauthentik.io error_page mapping and the @authentik_fail_closed location
itself — which no other gate covers. Dropping either re-opens the bypass.

CI-safe: template scan only; no Docker, no live system.
"""
from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
LOCATIONS_CONF = REPO / "templates/nginx/authentik-proxy-locations.conf"
AUTH_CONF = REPO / "templates/nginx/authentik-proxy-auth.conf"


def test_outpost_5xx_routes_to_fail_closed():
    """/outpost.goauthentik.io must map 500/502/503/504 to @authentik_fail_closed.

    A bare outpost-down (5xx) must deny, never bypass — otherwise an outpost DoS
    is an auth bypass for every proxy-auth service.
    """
    text = LOCATIONS_CONF.read_text()
    assert re.search(
        r"error_page\s+500\s+502\s+503\s+504\s*=\s*@authentik_fail_closed", text
    ), "outpost 5xx must route to @authentik_fail_closed (REM-048)"


def test_fail_closed_location_denies_with_503():
    """@authentik_fail_closed must exist and return 503 (deny), not 200 (allow)."""
    text = LOCATIONS_CONF.read_text()
    block = re.search(
        r"location\s+@authentik_fail_closed\s*\{(.*?)\}", text, re.DOTALL
    )
    assert block, "@authentik_fail_closed location must be declared (REM-048)"
    body = block.group(1)
    assert re.search(r"return\s+503\b", body), (
        "@authentik_fail_closed must return 503 — fail-closed denies access"
    )
    assert "return 200" not in body, (
        "@authentik_fail_closed must NOT return 200 — that re-opens the bypass"
    )


def test_bypass_location_only_returns_200_for_404():
    """@authentik_bypass returns 200, and ONLY 404 may route to it.

    Pins the locations.conf bypass intent and re-asserts the auth.conf mapping so
    a regression on either file fails this single REM-048 gate.
    """
    loc_text = LOCATIONS_CONF.read_text()
    bypass = re.search(
        r"location\s+@authentik_bypass\s*\{(.*?)\}", loc_text, re.DOTALL
    )
    assert bypass, "@authentik_bypass location must be declared"
    assert re.search(r"return\s+200\b", bypass.group(1)), (
        "@authentik_bypass returns 200 only for legitimate 404 path-not-found"
    )

    auth_text = AUTH_CONF.read_text()
    assert "error_page 404 = @authentik_bypass" in auth_text, (
        "only 404 may bypass auth (REM-048)"
    )
    assert not re.search(
        r"error_page[^\n]*\b(401|403|500|502|503|504)\b[^\n]*@authentik_bypass",
        auth_text,
    ), "401/403/5xx must never route to @authentik_bypass (REM-048)"


def test_no_5xx_bypass_anywhere_in_proxy_auth_configs():
    """Belt-and-suspenders: no 5xx error_page may point at @authentik_bypass.

    Comment lines (which document the OLD vulnerable mapping) are stripped first —
    only live nginx directives count.
    """
    for conf in (LOCATIONS_CONF, AUTH_CONF):
        directives = "\n".join(
            line for line in conf.read_text().splitlines()
            if not line.lstrip().startswith("#")
        )
        assert not re.search(
            r"error_page[^\n]*\b(500|502|503|504)\b[^\n]*@authentik_bypass", directives
        ), f"{conf.name}: 5xx must not bypass auth (REM-048 fail-closed)"
