#!/usr/bin/env python3
"""n8n-fire — Pulse clock for an n8n webhook workflow.

n8n does the hops. Pulse only POSTs. Args stay allowlist-safe (no JSON,
no quotes): --url= and --scope= are one token each.

  tools/n8n-fire.py --url=http://127.0.0.1:5678/webhook/nos-ares-registry --scope=all
  tools/n8n-fire.py --url=http://127.0.0.1:5678/webhook/nos-ares-registry --scope=missing

Exit 0 posted or idle (n8n down) · 2 webhook answered 4xx/5xx (inactive workflow).
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

UA = "nOS-pulse-n8n-fire/0.1"


def fire(url: str, scope: str, ico: str = "") -> int:
    body: dict = {"scope": scope}
    if ico:
        body["ico"] = ico
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json", "User-Agent": UA},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            if resp.status >= 400:
                print(f"n8n-fire: HTTP {resp.status}", file=sys.stderr)
                return 2
            print(f"n8n-fire: {url} scope={scope} HTTP {resp.status}", file=sys.stderr)
            return 0
    except urllib.error.HTTPError as e:
        print(f"n8n-fire: HTTP {e.code} (import+activate the template?)", file=sys.stderr)
        return 2
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        print(f"n8n-fire: idle (n8n not reachable: {e})", file=sys.stderr)
        return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True, help="production webhook URL")
    ap.add_argument("--scope", default="all", choices=["all", "missing", "ico"])
    ap.add_argument("--ico", default="", help="only with --scope=ico")
    args = ap.parse_args()
    if args.scope == "ico" and not args.ico:
        ap.error("--scope=ico needs --ico=")
    return fire(args.url, args.scope, args.ico)


if __name__ == "__main__":
    raise SystemExit(main())
