#!/usr/bin/env python3
"""Upsert EspoCRM Account rows from the KEAP party spine.

Join key lives in Account.description as `nos:party:<slug>` — no custom Espo
entity (the custom volume is a named Docker volume, not a bind from git).
Espo stays a CRM of relationships; KEAP stays the books. Dry by default.

  ESPO_URL=https://espocrm.apps.pazny.eu \\
  ESPO_API_KEY=... ESPO_API_USER=admin \\
  tools/espo-party-sync.py --dry-run

Needs KEAP_AGENT_TOKEN_RO (or the container) to read party rows.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "tools"))
import digest_absorb  # noqa: E402

MARKER = "nos:party:"


def account_payload(party: dict) -> dict:
    slug = party["slug"]
    name = party.get("legal_name") or slug
    desc = f"{MARKER}{slug}"
    notes = party.get("notes") or ""
    if notes:
        desc = f"{notes}\n{desc}"
    return {"name": name, "description": desc, "type": "Customer" if party.get("role") == "client" else "Partner"}


def _espo_get(base: str, path: str, hdr: dict) -> dict:
    req = urllib.request.Request(base.rstrip("/") + path, headers=hdr)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read() or b"{}")


def _espo_post(base: str, path: str, hdr: dict, body: dict) -> dict:
    req = urllib.request.Request(
        base.rstrip("/") + path, data=json.dumps(body).encode(),
        headers={**hdr, "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read() or b"{}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true", default=True)
    p.add_argument("--write", action="store_true", help="actually POST to Espo")
    args = p.parse_args(argv)
    write = args.write
    parties = [r for r in digest_absorb.read_rows("party") if r.get("slug")]
    payloads = [account_payload(r) for r in parties]
    if not write:
        json.dump({"would_upsert": len(payloads), "accounts": payloads}, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    base = os.environ.get("ESPO_URL", "").rstrip("/")
    user = os.environ.get("ESPO_API_USER", "")
    key = os.environ.get("ESPO_API_KEY", "")
    if not (base and user and key):
        print("REFUSING: ESPO_URL + ESPO_API_USER + ESPO_API_KEY required for --write", file=sys.stderr)
        return 2
    hdr = {"X-Api-Key": key, "X-User-Name": user}
    wrote = 0
    for body in payloads:
        marker = MARKER + body["description"].rsplit(MARKER, 1)[-1]
        q = urllib.parse.quote(marker)
        try:
            existing = _espo_get(base, f"/api/v1/Account?where[0][type]=contains&where[0][attribute]=description&where[0][value]={q}", hdr)
            rows = existing.get("list") or []
            if rows:
                print(f"  · {body['name']}: already {rows[0].get('id')}")
                continue
            _espo_post(base, "/api/v1/Account", hdr, body)
            print(f"  + {body['name']}")
            wrote += 1
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
            print(f"  FAIL {body['name']}: {exc}", file=sys.stderr)
            return 2
    print(f"upserted {wrote} of {len(payloads)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
