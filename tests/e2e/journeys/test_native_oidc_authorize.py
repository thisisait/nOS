"""E2E journey — every native_oidc provider accepts an authorization request.

Regression net for the v0.6-beta grant_types outage: Authentik 2026.5.x made
``OAuth2Provider.grant_types`` an explicit ArrayField; the tofu cutover
created providers without it (empty list) and EVERY native_oidc login died at
/authorize with ``invalid_request: "The request is otherwise malformed"`` —
while smoke + forward_auth journeys stayed green (the proxy path needs no
grant). This check needs no login: an UNAUTHENTICATED authorize request to a
healthy provider 302s INTO the Authentik auth flow (or renders it), while the
broken provider 302s straight BACK to the service callback with
``error=invalid_request``.

Runs against the live box (reads the committed registry + resolved domains
from Authentik's own provider list). Offline CI never sees this file —
tests/e2e is excluded from the anatomy suite.
"""

from __future__ import annotations

import pathlib
import urllib.parse
import urllib.request

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[3]
SECRETS = pathlib.Path.home() / ".nos" / "secrets.yml"
AUTHENTIK_API = "http://127.0.0.1:9003/api/v3"


def _token() -> str:
    if not SECRETS.is_file():
        pytest.skip("~/.nos/secrets.yml not present (no live tenant)")
    return yaml.safe_load(SECRETS.read_text())["authentik_bootstrap_token"]


def _get(url: str, token: str | None = None):
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    # Do NOT follow redirects — the Location header IS the verdict.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):  # noqa: D102
            return None

    opener = urllib.request.build_opener(NoRedirect)
    try:
        resp = opener.open(req, timeout=10)
        return resp.status, resp.headers.get("Location", "")
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Location", "")


def _oauth2_providers(token: str) -> list[dict]:
    import json

    req = urllib.request.Request(
        f"{AUTHENTIK_API}/providers/oauth2/?page_size=100",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        results = json.load(resp)["results"]
    # Service providers only. Agent clients (30-agent-clients blueprint) are
    # client_credentials machine clients — they reject authorization_code BY
    # DESIGN, so exclude exactly that declared shape. A provider with EMPTY
    # grant_types stays in: that's the outage signature this test exists for.
    return [
        p
        for p in results
        if p.get("redirect_uris") and p.get("grant_types") != ["client_credentials"]
    ]


def test_every_native_oidc_provider_accepts_authorize():
    token = _token()
    providers = _oauth2_providers(token)
    assert providers, "no oauth2 service providers found on the live tenant"
    broken: list[str] = []
    for p in providers:
        redirect = p["redirect_uris"][0]["url"]
        q = urllib.parse.urlencode(
            {
                "client_id": p["client_id"],
                "redirect_uri": redirect,
                "response_type": "code",
                "scope": "openid email profile",
                "state": "e2e-authorize-probe",
            }
        )
        status, location = _get(f"http://127.0.0.1:9003/application/o/authorize/?{q}")
        # Healthy: 302 into the auth flow (/if/flow/...) or 200 rendering it.
        # Broken (the grant_types signature): 302 back to the SERVICE callback
        # carrying error=invalid_request.
        if "error=" in (location or ""):
            err = urllib.parse.parse_qs(urllib.parse.urlparse(location).query)
            broken.append(f"{p['name']}: {err.get('error', ['?'])[0]}")
    assert not broken, (
        "native_oidc providers reject the authorize request (the v0.6-beta "
        f"grant_types outage signature): {broken}"
    )
