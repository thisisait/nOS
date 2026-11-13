#!/usr/bin/env python3
"""Create every declared identity's account in every SSO app — by logging in.

Native-OIDC and header-OIDC apps create a user on the first SSO login, so a
person who never opened an app had no account in it (nothing to share with,
no admin to promote). This logs each identity in to Authentik once and walks
each enabled app's `authentik.first_login` (tools/e2e-plan.py — the plugins
are the only list). Apps without a first_login are NAMED, never skipped silently.

  NOS_FIRST_LOGIN='[{"name": "akadmin", "password": "…"}]' \\
      tools/nos-first-login.py --auth-host auth.example [--local-tld]

Prints one line per identity × app; exit 1 if any declared walk failed.
--login-only stops after the Authentik login (tasks/verify-authentik-apps.yml).
"own_password": true marks a person whose password is theirs after the first
sign-in: a refused login is not a failure, an accepted one is named.
A failed login says why: "Authentik unreachable" (connection, timeout, 5xx) gets
no fix; "password refused" gets one FIX line naming the reapply door
(row operator-login-is-verified).
Passwords come only from the environment and are never printed.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import html
import os
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import requests  # noqa: E402  (nos_sso's own dependency)
from nos_sso import REACHED, login, loopback_for_unresolvable, tls_verify, walk  # noqa: E402


def _plan() -> list[dict]:
    spec = importlib.util.spec_from_file_location("e2e_plan", HERE / "e2e-plan.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.plan()


def sso_button(page: str, auth_host: str, app: str):
    """The page's own "Sign in with Authentik": a link to the authorize
    endpoint (WordPress, Dolibarr — it carries a one-time state) or a POST form
    to the app's oidc/oauth route (BookStack, GitLab — it carries a CSRF token)."""
    m = re.search(rf'href="(https://{re.escape(auth_host)}/application/o/authorize/[^"]+)"', page)
    if m:
        return ("GET", html.unescape(m.group(1)), None)
    m = re.search(r'<form[^>]*action="([^"]*(?:(?:oidc|oauth|sso)/login|/auth/openid_connect)[^"]*)"[^>]*method="POST"', page, re.I)
    if m:
        fields = dict(re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)"', page))
        return ("POST", urljoin(app, html.unescape(m.group(1))), {k: html.unescape(v) for k, v in fields.items()})
    return None


def landed(w, start: str, page: str = "", auth_host: str = "") -> bool:
    """On the app's own host, not on a login or error URL, and no SSO button
    left on the page (a login page at "/" is still a login page)."""
    u = urlparse(w.url)
    tail = (u.path + "?" + u.query).lower()
    return (w.outcome == REACHED and u.netloc == urlparse(start).netloc
            and not any(bad in tail for bad in ("login", "error", "link_account", "signin", "callback"))
            and not (page and sso_button(page, auth_host, w.url)))


def js_finish(sess, w, page: str, verify) -> bool | None:
    """Jellyfin's SSO-Auth callback page finishes in JS: it POSTs the state to
    /sso/OID/Auth/<provider>, and that POST creates the user. None = not such a page."""
    m = re.search(r"/sso/OID/Auth/([A-Za-z0-9_-]+)", page)
    if w.outcome != REACHED or not m:
        return None
    u = urlparse(w.url)
    body = {"deviceId": "nos-first-login", "deviceName": "nOS", "appName": "nOS first login",
            "appVersion": "1", "data": parse_qs(u.query).get("state", [""])[0]}
    r = sess.post(f"{u.scheme}://{u.netloc}/sso/OID/Auth/{m.group(1)}", json=body, timeout=20, verify=verify)
    return r.status_code == 200 and "AccessToken" in r.text


REAPPLY = "nos --tags authentik -e authentik_reapply=true"


def why_refused(exc: Exception) -> tuple[str, bool]:
    """(what to print, whether the reapply door fixes it). An outage is never sold as a password."""
    if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
        return f"Authentik unreachable ({type(exc).__name__})", False
    m = re.search(r"HTTP (\d{3})", str(exc))
    if m and m.group(1).startswith("5"):
        return f"Authentik unreachable (HTTP {m.group(1)})", False
    if "ak-stage-password" in str(exc) or (m and str(exc).endswith("at password")):
        return "password refused", True
    return f"authentik login refused ({exc})", False


def within_tier(ident: dict, row: dict) -> bool:
    """RBAC: tier 1 reaches every app, tier 4 only tier-4 apps. An identity
    walked into an app above its tier is refused by design, not a failure."""
    return not (ident.get("tier") and row.get("tier")) or int(ident["tier"]) <= int(row["tier"])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--auth-host", required=True)
    ap.add_argument("--local-tld", action="store_true", help="a local TLD: verify against the mkcert root CA")
    ap.add_argument("--login-only", action="store_true", help="the Authentik login alone, no app walk (--tags verify)")
    a = ap.parse_args(argv)
    identities = json.loads(os.environ.get("NOS_FIRST_LOGIN", "[]"))
    verify = tls_verify(a.local_tld)
    if a.local_tld:           # no DNS on Linux, the edge is on loopback
        loopback_for_unresolvable()
    apps = [] if a.login_only else [r for r in _plan() if r["mode"] in ("native_oidc", "header_oidc")]
    for r in apps:
        if not r.get("first_login"):
            why = r.get("first_login_blocked") or "no authentik.first_login declared"
            print(f"-     {r['slug']:<14} not created at install: {why}")
    failed = 0
    for ident in identities:
        name = ident["name"]
        try:
            sess = login(name, ident["password"], a.auth_host, verify=verify, scheme="https")
        except Exception as exc:  # noqa: BLE001
            if ident.get("own_password"):
                print(f"-     {name}: signs in with their own password now; app accounts came from the first walk")
                continue
            why, fixable = why_refused(exc)
            print(f"FAIL  {name}: {why}")
            if fixable:
                print(f"FIX   {name}: {REAPPLY} (restores the declared password)")
            failed += 1
            continue
        if a.login_only:
            print(f"ok    {name}: authentik login")
        if ident.get("own_password"):
            # The initial password is derivable from the secret master: a
            # temporary key, not the person's. Say so until they change it.
            print(f"!     {name}: still on the INITIAL password — they should change it at "
                  f"https://{a.auth_host}/if/user/#/settings")
        for r in apps:
            if not r.get("first_login"):
                continue
            realm = r.get("first_login_realm")
            if realm and realm not in (ident.get("realms") or ["authentik"]):
                print(f"-     {name} → {r['slug']}: only {realm}-realm identities enter it (refused by design)")
                continue
            if not within_tier(ident, r):
                print(f"-     {name} → {r['slug']}: a tier-{ident['tier']} identity may not open a tier-{r['tier']} app")
                continue
            w = walk(sess, r["first_login"], a.auth_host, verify=verify)
            page = w.body if w.outcome == REACHED else ""
            button = sso_button(page, a.auth_host, w.url) if page else None
            if button:                      # click it once, then judge
                method, url, data = button
                if method == "POST":
                    r2 = sess.post(url, data=data, headers={"Origin": f"{urlparse(url).scheme}://{urlparse(url).netloc}"},
                                   allow_redirects=False, timeout=20, verify=verify)
                    url = urljoin(url, r2.headers.get("location", url))
                w = walk(sess, url, a.auth_host, verify=verify)
                page = w.body if w.outcome == REACHED else ""
            finish = js_finish(sess, w, page, verify)
            ok = finish if finish is not None else landed(w, r["first_login"], page, a.auth_host)
            failed += not ok
            print(f"{'ok' if ok else 'FAIL':<5} {name} → {r['slug']}" + ("" if ok else f": {w.outcome} at {w.url[:120]}"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
