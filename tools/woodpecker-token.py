#!/usr/bin/env python3
"""Mint the Woodpecker personal token as an SSO identity — no browser, no form.

The token is what the UI shows under User Settings → Personal Access Tokens:
a JWT signed with the user's hash, no expiry, the same value on every call.
A person gets it by signing in to Woodpecker through Gitea, and to Gitea
through Authentik. This does the same over tools/nos_sso.py: log in to
Authentik, walk Gitea's "Sign in with Authentik", walk Woodpecker's grant,
then POST /api/user/token.

It used to POST Gitea's local sign-in form. That only worked while the
gitea-base extension was broken (2026-06-09 → 2026-09-30): once the form was
really hidden, Gitea answered 403 and every mint failed — as it would on
every blank. Only the token is printed, on stdout.

  SSO_PASSWORD=… tools/woodpecker-token.py --user akadmin \
      --auth-host auth.example --gitea-public https://git.example \
      --woodpecker-public https://ci.example
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from nos_sso import REACHED, login, walk  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", required=True, help="the Authentik identity the token belongs to")
    ap.add_argument("--auth-host", required=True)
    ap.add_argument("--gitea-public", required=True)
    ap.add_argument("--woodpecker-public", required=True)
    ap.add_argument("--insecure", action="store_true", help="local TLDs with a mkcert CA")
    a = ap.parse_args(argv)
    password = os.environ.get("SSO_PASSWORD", "")
    if not password:
        print("SSO_PASSWORD is empty", file=sys.stderr)
        return 2
    verify = not a.insecure
    gitea, wp = a.gitea_public.rstrip("/"), a.woodpecker_public.rstrip("/")

    try:
        s = login(a.user, password, a.auth_host, verify=verify, scheme=urlparse(gitea).scheme)
    except Exception as exc:  # noqa: BLE001
        print(f"authentik login refused: {exc}", file=sys.stderr)
        return 1
    # Gitea first: its session is what Woodpecker's grant needs.
    w = walk(s, f"{gitea}/user/oauth2/authentik", a.auth_host, verify=verify)
    if w.outcome != REACHED or urlparse(w.url).netloc != urlparse(gitea).netloc:
        print(f"gitea SSO: {w.outcome} at {w.url}", file=sys.stderr)
        return 1
    if "/user/link_account" in w.url:
        print("gitea SSO landed on link_account — enable oauth2_client auto registration", file=sys.stderr)
        return 1
    w = walk(s, f"{wp}/authorize", a.auth_host, verify=verify)
    if w.outcome != REACHED or not any(c.name == "user_sess" for c in s.cookies):
        print(f"woodpecker grant: {w.outcome} at {w.url}, no session", file=sys.stderr)
        return 1

    cfg = s.get(f"{wp}/web-config.js", timeout=20).text
    m = re.search(r'WOODPECKER_CSRF\s*=\s*"([^"]+)"', cfg)
    if not m:
        print("no WOODPECKER_CSRF in web-config.js", file=sys.stderr)
        return 1
    r = s.post(f"{wp}/api/user/token", headers={"X-CSRF-TOKEN": m.group(1)}, timeout=20)
    token = r.text.strip().strip('"')
    if r.status_code != 200 or not token:
        print(f"token mint failed: {r.status_code}", file=sys.stderr)
        return 1

    # The reader: the token must answer as JSON on a fresh, cookie-less call.
    import requests
    who = requests.get(f"{wp}/api/user", headers={"Authorization": f"Bearer {token}"},
                       timeout=20, verify=verify).json()
    if who.get("login") != a.user:
        print(f"token belongs to {who.get('login')!r}, not {a.user!r}", file=sys.stderr)
        return 1
    print(token)
    return 0


if __name__ == "__main__":
    sys.exit(main())
