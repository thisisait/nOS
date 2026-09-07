#!/usr/bin/env python3
"""Create / reconcile nOS DataTables in a standalone KEAP from state/keap-tables/.

The Ansible seeder (roles/pazny.keap/tasks/seed-face-table.yml) is the contract;
this is the same body over the same agent door, for a host that has no Ansible.
Idempotent: KEAP reconciles on re-POST (additive + relabel; a destructive change
answers 409 and is reported, never forced).

    seed-tables.py                      # roadmap + current-state
    seed-tables.py roadmap apps systems # named tables
    seed-tables.py --all                # every state/keap-tables/*.table.yml

Env: KEAP_API_URL (default http://127.0.0.1:8091), KEAP_AGENT_TOKEN_RW, NOS_SRC.
"""
import json
import os
import pathlib
import sys
import urllib.error
import urllib.request

import yaml

SRC = pathlib.Path(os.environ.get("NOS_SRC", "/srv/nos"))
TABLES = SRC / "state" / "keap-tables"
API = os.environ.get("KEAP_API_URL", "http://127.0.0.1:8091").rstrip("/")
TOKEN = os.environ.get("KEAP_AGENT_TOKEN_RW", "")
DEFAULT = ["roadmap", "current-state"]


def call(method, path, body=None):
    req = urllib.request.Request(
        f"{API}{path}", method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}


def body_for(slug, d):
    b = {
        "slug": slug,
        "title": d["title"],
        "description": d.get("description", ""),
        "driver": d.get("driver", "libsql"),
        "visibility": d.get("visibility", "tier-users"),
        "anchors": d.get("anchors", []),
        "columns": d["schema"]["columns"],
    }
    if "sharedWith" in d:
        b["sharedWith"] = d["sharedWith"]
    if "view" in d:
        b["view"] = d["view"]
    return b


def main(argv):
    if not TOKEN:
        sys.exit("KEAP_AGENT_TOKEN_RW is not set (source /etc/nos/keap-rw.env)")
    if "--all" in argv:
        slugs = sorted(p.name[: -len(".table.yml")] for p in TABLES.glob("*.table.yml"))
    else:
        slugs = [a for a in argv if not a.startswith("-")] or DEFAULT
    rc = 0
    for slug in slugs:
        f = TABLES / f"{slug}.table.yml"
        if not f.exists():
            print(f"{slug:16} MISSING {f}")
            rc = 1
            continue
        d = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        st, resp = call("POST", "/agent/v1/tables", body_for(slug, d))
        gst, g = call("GET", f"/agent/v1/tables/{slug}")
        data = g.get("data", g) if isinstance(g, dict) else {}
        tid = data.get("id") or data.get("table", {}).get("id") if isinstance(data, dict) else None
        verdict = {200: "reconciled", 201: "created", 409: "REFUSED (destructive change)",
                   404: "NO ROUTE", 401: "UNAUTHORIZED"}.get(st, f"HTTP {st}")
        print(f"{slug:16} {verdict:32} live={gst} id={tid}")
        if st not in (200, 201):
            rc = 1
            if resp:
                print("   ", json.dumps(resp)[:300])
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
