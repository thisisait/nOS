#!/usr/bin/env python3
"""Create every declared identity's account in every SSO app — by logging in.

Native-OIDC and header-OIDC apps create a user on the first SSO login, so a
person who never opened an app had no account in it (nothing to share with,
no admin to promote). This logs each identity in to Authentik once and walks
each enabled app's `authentik.first_login` (tools/e2e-plan.py — the plugins
are the only list). Apps without a first_login are NAMED, never skipped silently.

  NOS_FIRST_LOGIN='[{"name": "akadmin", "password": "…"}]' \\
      tools/nos-first-login.py --auth-host auth.example [--insecure]

Prints one line per identity × app; exit 1 if any declared walk failed.
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
from urllib.parse import urljoin, urlparse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from nos_sso import REACHED, login, walk  # noqa: E402


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


def within_tier(ident: dict, row: dict) -> bool:
    """RBAC: tier 1 reaches every app, tier 4 only tier-4 apps. An identity
    walked into an app above its tier is refused by design, not a failure."""
    return not (ident.get("tier") and row.get("tier")) or int(ident["tier"]) <= int(row["tier"])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--auth-host", required=True)
    ap.add_argument("--insecure", action="store_true", help="local TLDs with a mkcert CA")
    a = ap.parse_args(argv)
    identities = json.loads(os.environ.get("NOS_FIRST_LOGIN", "[]"))
    verify = not a.insecure
    apps = [r for r in _plan() if r["mode"] in ("native_oidc", "header_oidc")]
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
            print(f"FAIL  {name}: authentik login refused ({exc})")
            failed += 1
            continue
        for r in apps:
            if not r.get("first_login"):
                continue
            if not within_tier(ident, r):
                print(f"-     {name} → {r['slug']}: a tier-{ident['tier']} identity may not open a tier-{r['tier']} app")
                continue
            w = walk(sess, r["first_login"], a.auth_host, verify=verify)
            page = sess.get(w.url, timeout=20, verify=verify).text if w.outcome == REACHED else ""
            button = sso_button(page, a.auth_host, w.url) if page else None
            if button:                      # click it once, then judge
                method, url, data = button
                if method == "POST":
                    r2 = sess.post(url, data=data, headers={"Origin": f"{urlparse(url).scheme}://{urlparse(url).netloc}"},
                                   allow_redirects=False, timeout=20, verify=verify)
                    url = urljoin(url, r2.headers.get("location", url))
                w = walk(sess, url, a.auth_host, verify=verify)
                page = sess.get(w.url, timeout=20, verify=verify).text if w.outcome == REACHED else ""
            ok = landed(w, r["first_login"], page, a.auth_host)
            failed += not ok
            print(f"{'ok' if ok else 'FAIL':<5} {name} → {r['slug']}" + ("" if ok else f": {w.outcome} at {w.url[:120]}"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
