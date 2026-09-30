"""Journeys generated from what the configuration promises.

For every service the resolved config enables (tools/e2e-plan.py):
  * forward_auth / header_oidc — a tester AT the plugin's tier, logged in to
    Authentik, walks the launch URL and reaches the service host;
  * native_oidc — Authentik grants that tester an authorization code for the
    plugin's client_id and redirect_uri (the Authentik half of "Sign in with
    Authentik"; the app's own callback needs the app's state and is not here);
  * RBAC — a tester one tier BELOW the plugin's tier is refused.
No list lives here: add a plugin, enable it, and its journeys exist.
"""
from __future__ import annotations

from urllib.parse import urlencode, urlparse

import pytest

from conftest import load_plan
from lib.sso_walk import CODE, DENIED, REACHED, walk

try:
    PLAN = load_plan()
except Exception as exc:  # noqa: BLE001
    PLAN, _PLAN_ERROR = [], exc
CLAIMED = [s for s in PLAN if s["mode"] in ("forward_auth", "header_oidc") and s["tier"] and s["launch_url"]]
GATED = [s for s in CLAIMED if s["edge"] == "proxy"]
UNGATED_CLAIMS = [s for s in CLAIMED if s["edge"] != "proxy"]
NATIVE = [s for s in PLAN if s["mode"] == "native_oidc" and s["tier"] and s["client_id"] and s["redirect_uri"]]
BELOW = [s for s in GATED + NATIVE if s["tier"] < 4]
ids = lambda rows: [r["slug"] for r in rows]


def _authorize_url(auth_host: str, svc: dict) -> str:
    q = {"client_id": svc["client_id"], "redirect_uri": svc["redirect_uri"],
         "response_type": "code", "scope": "openid email profile", "state": "nos-e2e"}
    return f"https://{auth_host}/application/o/authorize/?{urlencode(q)}"


def test_the_plan_is_not_empty():
    assert PLAN, f"tools/e2e-plan.py produced no services ({globals().get('_PLAN_ERROR')})"


def test_every_enabled_service_resolves_to_a_url():
    """A service whose URL did not render would be skipped by every journey
    below — silently. Name it instead."""
    bad = {s["slug"]: s["unresolved"] for s in PLAN if s["unresolved"]}
    assert not bad, f"unresolved in the rendered plan: {bad}"


@pytest.mark.parametrize("svc", UNGATED_CLAIMS, ids=ids(UNGATED_CLAIMS))
def test_a_claimed_gate_is_enforced_at_the_edge(svc):
    """The plugin says forward_auth/header_oidc at tier N; Traefik puts no
    middleware in front (traefik_auth_modes). One of the two is wrong — this
    names the contradiction instead of choosing silently."""
    pytest.fail(f"{svc['slug']}: plugin authentik.mode={svc['mode']} tier {svc['tier']}, "
                f"but traefik_auth_modes says {svc['edge']!r} — anyone reaches {svc['launch_url']}")


@pytest.mark.parametrize("svc", GATED, ids=ids(GATED))
def test_an_anonymous_visitor_is_sent_to_authentik(svc, auth_host, verify_tls):
    import requests
    r = requests.get(svc["launch_url"], allow_redirects=False, verify=verify_tls, timeout=20,
                     headers={"Accept": "text/html"})
    assert r.is_redirect and auth_host in r.headers.get("location", ""), (
        f"{svc['slug']}: anonymous got {r.status_code} {r.headers.get('location', '')[:80]}")


@pytest.mark.parametrize("svc", GATED, ids=ids(GATED))
def test_a_tester_at_the_tier_reaches_the_service(svc, testers, auth_host, verify_tls):
    w = walk(testers(svc["tier"]), svc["launch_url"], auth_host, verify=verify_tls)
    assert w.outcome == REACHED and urlparse(w.url).netloc == urlparse(svc["launch_url"]).netloc, (
        f"{svc['slug']}: {w.outcome} at {w.url} ({w.status})\n  " + "\n  ".join(w.trail))


@pytest.mark.parametrize("svc", NATIVE, ids=ids(NATIVE))
def test_authentik_grants_a_code_to_a_tester_at_the_tier(svc, testers, auth_host, verify_tls):
    cb_host = urlparse(svc["redirect_uri"]).netloc
    w = walk(testers(svc["tier"]), _authorize_url(auth_host, svc), auth_host,
             verify=verify_tls, stop_at_code_for=cb_host)
    assert w.outcome == CODE, f"{svc['slug']}: {w.outcome} at {w.url}\n  " + "\n  ".join(w.trail)


@pytest.mark.parametrize("svc", BELOW, ids=ids(BELOW))
def test_a_tester_one_tier_below_is_refused(svc, testers, auth_host, verify_tls):
    sess = testers(svc["tier"] + 1)
    if svc["mode"] == "native_oidc":
        w = walk(sess, _authorize_url(auth_host, svc), auth_host, verify=verify_tls,
                 stop_at_code_for=urlparse(svc["redirect_uri"]).netloc)
    else:
        w = walk(sess, svc["launch_url"], auth_host, verify=verify_tls)
    assert w.outcome == DENIED, (
        f"{svc['slug']} (tier {svc['tier']}) let a tier-{svc['tier'] + 1} tester through: "
        f"{w.outcome} at {w.url}\n  " + "\n  ".join(w.trail))
