#!/usr/bin/env python3
"""Mint the Woodpecker personal token by walking the Gitea OAuth grant.

The token is what the UI shows under User Settings → Personal Access Tokens:
a JWT signed with the user's hash, no expiry, the same value on every call.
The UI obtains it by logging in through Gitea and POSTing /api/user/token,
and this script does exactly that over loopback, so a blank can have it
without a browser. Nothing is printed but the token on stdout.

  GITEA_PASSWORD=… tools/woodpecker-token.py --user pazny \
      --woodpecker http://127.0.0.1:8060 --gitea http://127.0.0.1:3003 \
      --gitea-public https://git.example --woodpecker-public https://ci.example
"""
from __future__ import annotations

import argparse
import html
import http.cookiejar
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):  # noqa: D401
        return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", required=True)
    ap.add_argument("--woodpecker", required=True)
    ap.add_argument("--gitea", required=True)
    ap.add_argument("--gitea-public", required=True)
    ap.add_argument("--woodpecker-public", required=True)
    args = ap.parse_args(argv)
    password = os.environ.get("GITEA_PASSWORD", "")
    if not password:
        print("GITEA_PASSWORD is empty", file=sys.stderr)
        return 2

    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar), NoRedirect)

    def call(method: str, url: str, data: dict | None = None, headers: dict | None = None):
        body = urllib.parse.urlencode(data).encode() if data is not None else None
        req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
        try:
            with opener.open(req, timeout=20) as r:
                out = r.status, r.headers, r.read().decode(errors="replace")
        except urllib.error.HTTPError as e:
            out = e.code, e.headers, e.read().decode(errors="replace")
        # Both services sit behind https and flag their cookies Secure; the
        # loopback hop is plain http, and urllib (unlike curl) honours the flag.
        for c in jar:
            c.secure = False
        return out

    def local(url: str) -> str:
        """Public redirect targets → the loopback ports the host can reach."""
        return url.replace(args.gitea_public.rstrip("/"), args.gitea.rstrip("/")) \
                  .replace(args.woodpecker_public.rstrip("/"), args.woodpecker.rstrip("/"))

    # 1. Woodpecker starts the dance; keep its state cookie.
    st, hd, _ = call("GET", f"{args.woodpecker}/authorize")
    if st not in (302, 303) or "/login/oauth/authorize" not in hd.get("Location", ""):
        print(f"woodpecker /authorize did not redirect to the forge: {st}", file=sys.stderr)
        return 1
    authorize_url = local(hd["Location"])

    # 2. Gitea session (the login POST is served even when the form is hidden).
    st, hd, _ = call("POST", f"{args.gitea}/user/login",
                     {"user_name": args.user, "password": password})
    if st not in (302, 303) or "/user/login" in hd.get("Location", ""):
        print(f"gitea login refused: {st}", file=sys.stderr)
        return 1

    # 3. Authorize page: already granted → redirect; else POST the grant form.
    st, hd, body = call("GET", authorize_url)
    if st == 200:
        fields = {html.unescape(k): html.unescape(v) for k, v in
                  re.findall(r'<input[^>]+name="([^"]+)"[^>]+value="([^"]*)"', body)}
        fields.setdefault("granted", "true")   # Gitea 1.27 takes the grant without _csrf
        st, hd, body = call("POST", f"{args.gitea}/login/oauth/grant", fields)
    if st not in (302, 303) or "code=" not in hd.get("Location", ""):
        print(f"gitea did not issue a code: {st}", file=sys.stderr)
        return 1

    # 4. Callback into Woodpecker → user session cookie.
    st, hd, body = call("GET", local(hd["Location"]))
    if not any(c.name == "user_sess" for c in jar):
        print(f"woodpecker callback set no session: {st} {body[:120]!r}", file=sys.stderr)
        return 1

    # 5. CSRF from web-config.js, then the token the UI shows.
    _, _, cfg = call("GET", f"{args.woodpecker}/web-config.js")
    m = re.search(r'WOODPECKER_CSRF\s*=\s*"([^"]+)"', cfg)
    if not m:
        print("no WOODPECKER_CSRF in web-config.js", file=sys.stderr)
        return 1
    st, _, tok = call("POST", f"{args.woodpecker}/api/user/token", headers={"X-CSRF-TOKEN": m.group(1)})
    token = tok.strip().strip('"')
    if st != 200 or not token:
        print(f"token mint failed: {st}", file=sys.stderr)
        return 1

    # 6. The reader: the token must answer as JSON on a fresh, cookie-less call.
    req = urllib.request.Request(f"{args.woodpecker}/api/user", headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=20) as r:
        who = json.loads(r.read().decode())
    if who.get("login") != args.user:
        print(f"token belongs to {who.get('login')!r}, not {args.user!r}", file=sys.stderr)
        return 1
    print(token)
    return 0


if __name__ == "__main__":
    sys.exit(main())
