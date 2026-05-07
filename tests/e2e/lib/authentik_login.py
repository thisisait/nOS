"""Headless Authentik flow-executor login (A13.6).

Drives the same flow that ``tools/nos-smoke.py::_try_authentik_login`` uses,
but exposes a clean ``requests.Session`` API for journey tests.

How Authentik headless auth works:
    1. GET  /api/v3/flows/executor/<slug>/    — primes the flow + sets cookie
    2. POST /api/v3/flows/executor/<slug>/    — body: {"uid_field": <username>}
    3. POST /api/v3/flows/executor/<slug>/    — body: {"password": <password>}
The returned cookies (authentik session) are then valid for the proxy outpost,
so subsequent requests through Traefik forward-auth get
``X-Authentik-Username``/``-Groups`` headers stamped automatically.

Caveats:
    * Default flow slug is ``default-authentication-flow`` (Authentik 2024.2+).
      Override via ``AUTHENTIK_FLOW_SLUG`` if the operator deviated.
    * If Authentik is on a public LE-issued domain we hit it directly. For
      loopback dev (mkcert) we still talk to the public name (``auth.<tld>``)
      — that's the only host the cookie will be valid for, since the cookie
      domain is ``.<tld>`` (cross-subdomain SSO).
    * ``ignore_tls`` is on by default to mirror the smoke runner (mkcert dev
      certs aren't always in the keychain when CI runs).
"""

from __future__ import annotations

import os
import urllib3

import requests


DEFAULT_FLOW_SLUG = "default-authentication-flow"


class AuthentikLoginError(RuntimeError):
    pass


def _authentik_domain() -> str:
    """Resolve the Authentik public domain. Required for cookie validity."""
    explicit = os.environ.get("AUTHENTIK_DOMAIN")
    if explicit:
        return explicit
    # Fall back to dev convention: auth.<tenant_domain>
    tenant = os.environ.get("NOS_HOST") or os.environ.get("TENANT_DOMAIN") or "dev.local"
    return f"auth.{tenant}"


def login_session(username: str, password: str,
                  flow_slug: str | None = None,
                  authentik_domain: str | None = None,
                  ignore_tls: bool = True,
                  timeout_s: float = 10) -> requests.Session:
    """Drive the Authentik flow executor headlessly. Returns a requests.Session
    whose cookie jar carries the authenticated session — pass it through to
    your subsequent requests-through-Traefik calls.

    Raises ``AuthentikLoginError`` on any failure with a descriptive message.
    """
    if flow_slug is None:
        flow_slug = os.environ.get("AUTHENTIK_FLOW_SLUG", DEFAULT_FLOW_SLUG)
    if authentik_domain is None:
        authentik_domain = _authentik_domain()

    if ignore_tls:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    base = f"https://{authentik_domain}/api/v3/flows/executor/{flow_slug}/"
    sess = requests.Session()
    sess.headers.update({
        "User-Agent": "nos-e2e-tester/1.0 (auth-flow)",
        "Accept": "application/json",
    })

    # Stage 1: prime
    try:
        sess.get(base, timeout=timeout_s, verify=not ignore_tls)
    except requests.RequestException as exc:
        raise AuthentikLoginError(f"flow prime GET failed: {exc}") from exc

    # Stage 2: identification
    try:
        r = sess.post(
            base, json={"uid_field": username},
            timeout=timeout_s, verify=not ignore_tls,
        )
    except requests.RequestException as exc:
        raise AuthentikLoginError(f"identification POST failed: {exc}") from exc
    if r.status_code >= 400:
        raise AuthentikLoginError(f"identification HTTP {r.status_code}: {r.text[:200]}")

    # Stage 3: password
    try:
        r = sess.post(
            base, json={"password": password},
            timeout=timeout_s, verify=not ignore_tls,
        )
    except requests.RequestException as exc:
        raise AuthentikLoginError(f"password POST failed: {exc}") from exc
    if r.status_code >= 400:
        raise AuthentikLoginError(f"password HTTP {r.status_code}: {r.text[:200]}")

    body = {}
    try:
        body = r.json()
    except (ValueError, requests.JSONDecodeError):
        pass
    component = body.get("component", "") if isinstance(body, dict) else ""
    if "access-denied" in component or "deny" in component:
        raise AuthentikLoginError(f"flow ended with denial: component={component}")

    # Persist the ignore_tls choice on the session so the caller's downstream
    # GETs through Traefik don't accidentally re-validate against a missing CA.
    sess.verify = not ignore_tls
    return sess
