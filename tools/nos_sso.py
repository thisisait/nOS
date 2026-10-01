"""Log in to Authentik and walk a URL as a person would — no browser.

One implementation for the E2E journeys (tests/e2e/lib/sso_walk.py re-exports
it) and for tools that must act as an operator through SSO
(tools/woodpecker-token.py): `login()` drives the flow executor, `walk()`
follows redirects by hand and runs /if/flow/ pages through the executor API.
A walk ends REACHED (a non-auth host answered below 400), DENIED (Authentik's
permission-denied page or stage), CODE (stopped at a redirect carrying code=)
or STUCK (with the trail, so a failure names the hop).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import parse_qs, urljoin, urlparse

import requests

REACHED, DENIED, STUCK, CODE = "reached", "denied", "stuck", "code"


@dataclass
class Walk:
    outcome: str
    url: str
    status: int | None = None
    trail: list[str] = field(default_factory=list)


def _flow(sess: requests.Session, url: str, verify: bool) -> tuple[str | None, str | None]:
    """Run /if/flow/<slug>/?<query> through the executor. Returns (next_url, denial)."""
    u = urlparse(url)
    slug = u.path.split("/if/flow/", 1)[1].strip("/").split("/")[0]
    api = f"{u.scheme}://{u.netloc}/api/v3/flows/executor/{slug}/"
    params = {"query": u.query}
    js = {"Accept": "application/json"}
    r = sess.get(api, params=params, headers=js, verify=verify, timeout=20)
    for _ in range(6):
        c = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        comp = c.get("component", "")
        if comp == "xak-flow-redirect":
            return urljoin(url, c.get("to", "")), None
        if comp == "ak-stage-access-denied":
            return None, c.get("error_message") or "access denied"
        if comp == "ak-stage-consent":
            r = sess.post(api, params=params, json={"token": c.get("token", "")}, headers=js,
                          verify=verify, timeout=20)
            continue
        return None, f"unhandled flow component {comp or r.status_code}"
    return None, "flow did not finish"


def walk(sess: requests.Session, url: str, auth_host: str, verify: bool = True,
         stop_at_code_for: str | None = None, max_hops: int = 15) -> Walk:
    """Follow `url`. With `stop_at_code_for=<redirect host>`, stop at the first
    hop to that host carrying `code=` (the Authentik half of native OIDC)."""
    trail: list[str] = []
    # Per request, not on the session: login_session() leaves the session
    # asking for JSON (the flow executor's), and FreeScout answered that JSON
    # 401 to an authenticated tester — a browser asking for HTML gets /login.
    html = {"Accept": "text/html,application/xhtml+xml,*/*;q=0.8"}
    for _ in range(max_hops):
        trail.append(url)
        u = urlparse(url)
        if stop_at_code_for and u.netloc == stop_at_code_for and "code" in parse_qs(u.query):
            return Walk(CODE, url, None, trail)
        if u.netloc == auth_host and u.path.startswith("/if/flow/"):
            nxt, denial = _flow(sess, url, verify)
            if denial:
                return Walk(DENIED, url, None, trail + [f"denied: {denial}"])
            if not nxt:
                return Walk(STUCK, url, None, trail)
            url = nxt
            continue
        r = sess.get(url, allow_redirects=False, headers=html, verify=verify, timeout=20)
        if r.is_redirect or r.status_code in (301, 302, 303, 307, 308):
            url = urljoin(url, r.headers.get("location", ""))
            continue
        if u.netloc != auth_host and r.status_code < 400:
            return Walk(REACHED, url, r.status_code, trail)
        # A policy refusal is NOT a flow: /application/o/authorize/ answers
        # 200 with the "Permission denied - authentik" page (measured 2026-09-30).
        if u.netloc == auth_host and "Permission denied - authentik" in r.text:
            return Walk(DENIED, url, r.status_code, trail + ["denied: Permission denied page"])
        return Walk(STUCK, url, r.status_code, trail)
    return Walk(STUCK, url, None, trail + ["too many hops"])


def loopback_for_unresolvable() -> None:
    """Local TLDs on Linux have no resolver (/etc/resolver is macOS-only), so
    auth.dev.local failed DNS in the wet-test while the edge on 127.0.0.1
    served it — nos-smoke retries the same way. A name that does not resolve
    connects to 127.0.0.1; Host and SNI keep the name, so routing is tested."""
    import socket

    import urllib3.util.connection as uc
    if getattr(uc.create_connection, "_nos_loopback", False):
        return
    original = uc.create_connection

    def create_connection(address, *args, **kwargs):
        host, port = address
        try:
            socket.getaddrinfo(host, port)
        except socket.gaierror:
            address = ("127.0.0.1", port)
        return original(address, *args, **kwargs)

    create_connection._nos_loopback = True
    uc.create_connection = create_connection


def login(username: str, password: str, auth_host: str, verify: bool = True,
          flow_slug: str = "default-authentication-flow", timeout: float = 20,
          scheme: str = "https") -> requests.Session:
    """Identification + password through the flow executor; the returned
    session carries the Authentik cookies. Raises RuntimeError on refusal."""
    api = f"{scheme}://{auth_host}/api/v3/flows/executor/{flow_slug}/"
    s = requests.Session()
    s.verify = verify
    js = {"Accept": "application/json"}
    s.get(api, headers=js, timeout=timeout)
    for body in ({"uid_field": username}, {"password": password}):
        r = s.post(api, json=body, headers=js, timeout=timeout)
        if r.status_code >= 400:
            raise RuntimeError(f"authentik login: HTTP {r.status_code} at {list(body)[0]}")
    comp = (r.json() if r.headers.get("content-type", "").startswith("application/json") else {}).get("component", "")
    if comp != "xak-flow-redirect":
        raise RuntimeError(f"authentik login did not finish: {comp or r.status_code}")
    return s
