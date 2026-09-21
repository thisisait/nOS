#!/usr/bin/env python3
"""Upsert EspoCRM Account rows from the KEAP party spine.

Join key lives in Account.description as `nos:party:<slug>` — no custom Espo
entity (the custom volume is a named Docker volume, not a bind from git).
Espo stays a CRM of relationships; KEAP stays the books. Dry by default.

Auth is autowired from the running container (same bootstrap admin the
apps_runner OIDC PUT uses). Override with ESPO_URL / ESPO_API_KEY /
ESPO_ADMIN_PASSWORD only when you are not on the estate.

  tools/espo-party-sync.py              # dry-run
  tools/espo-party-sync.py --write      # POST new / PUT existing Account rows

Needs KEAP_AGENT_TOKEN_RO (or the container) to read party rows.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "tools"))
import digest_absorb  # noqa: E402

MARKER = "nos:party:"
# Exact join slug: `contains nos:party:alfa` must not also hit `…alfa-customer`.
JOIN_SLUG_RE = re.compile(rf"(?:^|\n){re.escape(MARKER)}([a-z0-9-]+)(?:\n|$)")
ICO_IN_NAME = re.compile(r"(?<!\d)\d{8}(?!\d)")
ESPO_CONTAINER = os.environ.get("ESPO_CONTAINER", "espocrm")


def join_slug_from_description(desc: str) -> str | None:
    m = JOIN_SLUG_RE.search(desc or "")
    return m.group(1) if m else None


def index_accounts_by_slug(rows: list) -> dict:
    out: dict = {}
    for r in rows:
        slug = join_slug_from_description(r.get("description") or "")
        if slug:
            out[slug] = r
    return out


def skip_espo_party(party: dict) -> bool:
    """Vision mash put the IČO into legal_name; the real party already exists."""
    return bool(ICO_IN_NAME.search(party.get("legal_name") or ""))


def account_payload(party: dict) -> dict:
    slug = party["slug"]
    name = party.get("legal_name") or slug
    desc = f"{MARKER}{slug}"
    notes = party.get("notes") or ""
    if notes:
        desc = f"{notes}\n{desc}"
    kind = (party.get("notes") or "") + " " + (party.get("party_kind") or "")
    customer = "client" in kind.lower() or party.get("role") == "client"
    return {"name": name, "description": desc, "type": "Customer" if customer else "Partner"}


def _docker_env(key: str, container: str = ESPO_CONTAINER) -> str:
    try:
        out = subprocess.run(
            ["docker", "exec", container, "printenv", key],
            capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def espo_base_url() -> str:
    return (os.environ.get("ESPO_URL") or _docker_env("ESPOCRM_SITE_URL") or "").rstrip("/")


def espo_auth_headers() -> dict:
    """Prefer an explicit API key; else the bootstrap admin already in compose."""
    key = os.environ.get("ESPO_API_KEY", "").strip()
    user = os.environ.get("ESPO_API_USER", "").strip()
    if key:
        return {"X-Api-Key": key, "X-User-Name": user or "admin",
                "Content-Type": "application/json"}
    pw = os.environ.get("ESPO_ADMIN_PASSWORD", "").strip() or _docker_env("ESPOCRM_ADMIN_PASSWORD")
    user = user or _docker_env("ESPOCRM_ADMIN_USERNAME") or "admin"
    if not pw:
        return {}
    token = base64.b64encode(f"{user}:{pw}".encode()).decode()
    return {"Authorization": f"Basic {token}", "Content-Type": "application/json"}


def _espo_get(base: str, path: str, hdr: dict) -> dict:
    req = urllib.request.Request(base.rstrip("/") + path, headers=hdr)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read() or b"{}")


def _espo_post(base: str, path: str, hdr: dict, body: dict) -> dict:
    req = urllib.request.Request(
        base.rstrip("/") + path, data=json.dumps(body).encode(),
        headers=hdr, method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read() or b"{}")


def _espo_put(base: str, path: str, hdr: dict, body: dict) -> dict:
    req = urllib.request.Request(
        base.rstrip("/") + path, data=json.dumps(body).encode(),
        headers=hdr, method="PUT")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read() or b"{}")


def upsert_account(base: str, hdr: dict, body: dict, existing: list) -> str:
    """POST a new Account or PUT the first row that already carries the join tag."""
    if existing:
        aid = existing[0].get("id")
        _espo_put(base, f"/api/v1/Account/{aid}", hdr, body)
        return f"put:{aid}"
    _espo_post(base, "/api/v1/Account", hdr, body)
    return "post"


def list_accounts(base: str, hdr: dict) -> list:
    rows: list = []
    offset = 0
    while True:
        data = _espo_get(base, f"/api/v1/Account?maxSize=200&offset={offset}", hdr)
        chunk = data.get("list") or []
        rows.extend(chunk)
        total = data.get("total")
        if not chunk or (isinstance(total, int) and len(rows) >= total) or len(chunk) < 200:
            break
        offset += 200
    return rows


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true", default=True)
    p.add_argument("--write", action="store_true", help="actually POST to Espo")
    args = p.parse_args(argv)
    write = args.write
    parties = [
        r for r in digest_absorb.read_rows("party")
        if r.get("slug") and not skip_espo_party(r)
    ]
    payloads = [account_payload(r) for r in parties]
    if not write:
        json.dump({"would_upsert": len(payloads), "accounts": payloads}, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    base = espo_base_url()
    hdr = espo_auth_headers()
    if not (base and hdr):
        print("REFUSING: no Espo URL/admin — container env empty and no ESPO_* override",
              file=sys.stderr)
        return 2
    try:
        by_slug = index_accounts_by_slug(list_accounts(base, hdr))
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
        print(f"REFUSING: cannot list Espo Accounts: {exc}", file=sys.stderr)
        return 2
    wrote = 0
    for body in payloads:
        slug = join_slug_from_description(body["description"])
        hit = by_slug.get(slug) if slug else None
        try:
            action = upsert_account(base, hdr, body, [hit] if hit else [])
            print(f"  + {body['name']}: {action}")
            wrote += 1
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
            print(f"  FAIL {body['name']}: {exc}", file=sys.stderr)
            return 2
    print(f"upserted {wrote} of {len(payloads)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
