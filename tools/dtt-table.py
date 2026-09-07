#!/usr/bin/env python3
"""Your own DataTables: list, create from a template, share, resolve — as YOU.

The human door already holds the whole share model (owner, visibility grade,
per-principal read/write grants); what the CLI lacked was an identity. Behind
the identity outpost (KEAP_IDENTITY_URL, tools/keap_api.py) every call here is
made as the Linux user running it, so a table you create is yours, private by
default, and a grant is something only you (or an admin) can give.

    nos dtt tables                                   # what you can see, and whose it is
    nos dtt create-table "Project X" [--template roadmap] [--visibility private|shared]
    nos dtt share "Project X" --with user:svp2bj --access read|write|none
    nos dtt --table "Project X" status|capture|seed|update …   # every verb, on that table

`--template` is a file in state/keap-tables/<name>.table.yml (columns, anchors,
view); the default `roadmap` gives a project the same shape as the estate's plan.
A table is addressed by its id or, when unambiguous, its title.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from keap_api import human_base, human_headers, via_identity  # noqa: E402

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TABLES = os.path.join(REPO, "state", "keap-tables")


def _die(msg: str) -> None:
    sys.exit(f"REFUSING: {msg}")


def req(method: str, path: str, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(f"{human_base()}{path}", data=data, headers=human_headers(), method=method)
    try:
        with urllib.request.urlopen(r, timeout=30) as x:
            return x.status, json.loads(x.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:  # noqa: BLE001
            return e.code, {}
    except urllib.error.URLError as e:
        _die(f"KEAP unreachable at {human_base()}: {e.reason}")


def tables() -> list[dict]:
    st, d = req("GET", "/api/tables")
    if st != 200:
        _die(f"cannot list tables ({st}): {d.get('error', d)}")
    return d.get("data", [])


def resolve(ref: str) -> dict:
    ts = tables()
    hit = [t for t in ts if t.get("id") == ref]
    if not hit:
        hit = [t for t in ts if (t.get("title") or "").strip().lower() == ref.strip().lower()]
    if not hit:
        _die(f"no table you can see is called `{ref}` — `nos dtt tables` lists yours")
    if len(hit) > 1:
        _die(f"`{ref}` matches {len(hit)} tables; use the id: " + ", ".join(t["id"] for t in hit))
    return hit[0]


def cmd_list(a) -> int:
    me = os.environ.get("USER", "?")
    ts = tables()
    if not ts:
        print("no tables visible to you"); return 0
    for t in ts:
        owner = t.get("ownerId") or t.get("owner") or "?"
        grants = ", ".join(f"{g['principal']}:{g['access']}" for g in (t.get("sharedWith") or [])) or "—"
        mine = "mine" if owner == me else f"by {owner}"
        print(f"{t['id']}  {t.get('visibility','?'):14} {mine:18} {t.get('title','')}   grants: {grants}")
    return 0


def cmd_create(a) -> int:
    tpl = os.path.join(TABLES, f"{a.template}.table.yml")
    if not os.path.exists(tpl):
        _die(f"no template {a.template} (state/keap-tables/{a.template}.table.yml)")
    d = yaml.safe_load(open(tpl, encoding="utf-8")) or {}
    body = {
        "title": a.title,
        "description": a.description or f"{a.title} — a {a.template}-shaped table, created with nos dtt create-table",
        "driver": d.get("driver", "libsql"),
        "visibility": a.visibility,
        "schema": {"columns": d["schema"]["columns"]},
        "anchors": [],
    }
    if "view" in d:
        body["view"] = d["view"]
    if a.dry_run:
        print(json.dumps(body, indent=1)); return 0
    st, r = req("POST", "/api/tables", body)
    if st != 200:
        _die(f"create failed ({st}): {r.get('error', r)}")
    t = r.get("data", r)
    print(f"created {t['id']}  {t.get('visibility')}  {t.get('title')}")
    print(f"  use it: nos dtt --table {t['id']} status   (or --table \"{a.title}\")")
    return 0


def cmd_share(a) -> int:
    t = resolve(a.table)
    if not a.principal.startswith(("user:", "agent:")):
        _die("--with takes a principal: user:<login> or agent:<name>")
    grants = [g for g in (t.get("sharedWith") or []) if g.get("principal") != a.principal]
    if a.access != "none":
        grants.append({"principal": a.principal, "access": a.access})
    st, r = req("PATCH", f"/api/tables/{t['id']}", {"sharedWith": grants})
    if st != 200:
        _die(f"share failed ({st}): {r.get('error', r)} — only the owner or an admin may share")
    print(f"{t.get('title')}: " + (", ".join(f"{g['principal']}:{g['access']}" for g in grants) or "no grants"))
    return 0


def cmd_visibility(a) -> int:
    t = resolve(a.table)
    st, r = req("PATCH", f"/api/tables/{t['id']}", {"visibility": a.grade})
    if st != 200:
        _die(f"visibility change failed ({st}): {r.get('error', r)}")
    print(f"{t.get('title')}: visibility {a.grade}")
    return 0


def cmd_resolve(a) -> int:
    print(resolve(a.table)["id"]); return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list").set_defaults(fn=cmd_list)
    c = sub.add_parser("create"); c.add_argument("title"); c.add_argument("--template", default="roadmap")
    c.add_argument("--visibility", default="private", choices=["private", "shared", "tier-managers", "tier-users", "tier-guests", "public"])
    c.add_argument("--description", default=""); c.add_argument("--dry-run", action="store_true"); c.set_defaults(fn=cmd_create)
    s = sub.add_parser("share"); s.add_argument("table"); s.add_argument("--with", dest="principal", required=True)
    s.add_argument("--access", default="read", choices=["read", "write", "none"]); s.set_defaults(fn=cmd_share)
    v = sub.add_parser("visibility"); v.add_argument("table"); v.add_argument("grade", choices=["private", "shared", "tier-managers", "tier-users", "tier-guests", "public"]); v.set_defaults(fn=cmd_visibility)
    r = sub.add_parser("resolve"); r.add_argument("table"); r.set_defaults(fn=cmd_resolve)
    a = ap.parse_args()
    if not via_identity() and a.cmd in ("create", "share", "visibility"):
        print("note: no identity outpost (KEAP_IDENTITY_URL unset) — acting as the estate admin, "
              "so the table will be owned by akadmin, not you", file=sys.stderr)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
