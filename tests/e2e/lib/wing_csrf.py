"""Browser-faithful CSRF POST helper for the e2e journeys.

SEC-14 (2026-05-23): Wing's state-changing POST actions call
BasePresenter::requirePostMethod() → validateCsrfToken(), which checks a
session-bound `_csrf` field against the Nette session token. A stateless
header-auth POST (what the journeys used to do) has no session + no token →
403. This helper replays the real browser flow:

  1. GET a page that renders the form (mints the session + CSRF token, sets
     the session cookie) — carrying the same edge + forward-auth headers
     Traefik injects, so it passes the SEC-6 edge gate + RBAC.
  2. Scrape the form's hidden `_csrf` value.
  3. POST with the SAME cookie jar (session persists → token matches) + the
     `_csrf` field (and any extra form fields).

Returns (status, body, location_header) — mirroring the journeys' helpers.
"""

from __future__ import annotations

import http.cookiejar
import os
import re
import urllib.error
import urllib.parse
import urllib.request

_CSRF_RE = re.compile(r'name="_csrf"\s+value="([^"]+)"')


def _with_edge(headers: dict) -> dict:
    """SEC-6: inject Traefik's X-Wing-Edge-Token so both the GET and POST pass
    Wing's edge gate (which runs before RBAC + CSRF)."""
    out = dict(headers or {})
    edge = os.environ.get("WING_EDGE_TOKEN", "")
    if edge:
        out.setdefault("X-Wing-Edge-Token", edge)
    return out


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):  # noqa: ANN001
        return None


def csrf_post(wing_url: str, get_path: str, post_path: str, *,
              headers: dict, extra_post: dict | None = None,
              ) -> tuple[int, str, str]:
    wing_url = wing_url.rstrip("/")
    headers = _with_edge(headers)
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(jar), _NoRedirect())

    # 1+2: GET the form page → mint session + token, scrape _csrf.
    try:
        gresp = opener.open(
            urllib.request.Request(wing_url + get_path, headers=headers), timeout=5)
        html = gresp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, f"GET {get_path} for CSRF failed", ""
    except (urllib.error.URLError, OSError) as e:
        return 0, str(e), ""
    m = _CSRF_RE.search(html)
    if not m:
        return 0, f"no _csrf field in {get_path} response", ""

    # 3: POST with the session cookie + the scraped token.
    body = {"_csrf": m.group(1), **(extra_post or {})}
    data = urllib.parse.urlencode(body).encode()
    try:
        presp = opener.open(
            urllib.request.Request(wing_url + post_path, data=data,
                                   headers=headers, method="POST"), timeout=5)
        return presp.status, presp.read().decode("utf-8", "replace"), \
            presp.headers.get("Location", "")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), \
            e.headers.get("Location", "") if e.headers else ""
    except (urllib.error.URLError, OSError) as e:
        return 0, str(e), ""
