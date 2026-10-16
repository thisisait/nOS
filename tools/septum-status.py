#!/usr/bin/env python3
"""The septum: which KEAP tables hold a client's data, and is that said.

    tools/septum-status.py                  declarations + live rows (KEAP RO)
    tools/septum-status.py --rows-json F    rows from a {table: [rows]} file
    tools/septum-status.py --json

Reads `client_scope:` from state/keap-tables/*.table.yml (vocabulary and gate:
tests/anatomy/test_septum_scope_declared.py). RED: a table with no or an unknown
scope, `unresolved` (holds client data, no column names the client), or orphan
rows (a set ref whose target row is gone: offboarding would miss them), a live
table whose visibility is not its def's (KEAP may set it on create only). WARN: a
`personal` table that is not `visibility: private`; unstamped rows (no book_owner on
their path). Live: parties by role, rows per client. KEAP unreachable = UNKNOWN.
A declaration only: KEAP enforces no per-row owner yet. A READER, exits 0.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
TABLES = REPO / "state" / "keap-tables"
FIXED = {"none", "personal", "self", "book_owner", "unresolved"}
WALKS = {"self", "book_owner"}
ORPHAN = "\0orphan"  # a ref is set but its target row is gone: no path to any owner
UNSTAMPED = "\0unstamped"  # a book_owner-scoped row that names no book: whose is unknown


def load_defs(root: Path = TABLES) -> dict[str, dict]:
    return {p.name.removesuffix(".table.yml"): yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            for p in sorted(root.glob("*.table.yml"))}


def walks(scope) -> bool:
    return isinstance(scope, str) and (scope in WALKS or scope.startswith("rowRef:"))


def declarations(defs: dict) -> tuple[list[str], list[str]]:
    red, warn = [], []
    for name, d in defs.items():
        s = d.get("client_scope")
        if s is None:
            red.append(f"{name}: no client_scope")
        elif not (s in FIXED or walks(s)):
            red.append(f"{name}: client_scope {s!r} is not in the vocabulary")
        elif s == "unresolved":
            red.append(f"{name}: unresolved — holds client data, no column names the client")
        elif s == "personal" and d.get("visibility") != "private":
            warn.append(f"{name}: personal, but visibility {d.get('visibility')!r} (not private)")
    return red, warn


def _ref_table(d: dict, col: str) -> str | None:
    for c in (d.get("schema") or {}).get("columns") or []:
        if c.get("key") == col:
            return c.get("refTable")
    return None


def client_of(table: str, row: dict, defs: dict, rows: dict, roles: dict, depth: int = 0):
    """The client party slug this row walks to, None (own books, counterparty), or ORPHAN."""
    s = defs[table].get("client_scope")
    if depth > 8:
        return ORPHAN
    if not walks(s):
        return None
    if s == "self":
        slug = row.get("slug")
        return slug if roles.get(slug) == "client" else None
    col = "book_owner" if s == "book_owner" else s.split(":", 1)[1]
    target, val = _ref_table(defs[table], col), row.get(col)
    if not val and s == "book_owner":  # at any depth: a child inherits the unknown book
        return UNSTAMPED
    if not val or not target:
        return None
    if target == "party":
        return ORPHAN if val not in roles else (val if roles[val] == "client" else None)
    parent = next((r for r in rows.get(target) or [] if r.get("slug") == val), None)
    return client_of(target, parent, defs, rows, roles, depth + 1) if parent else ORPHAN


def live(defs: dict, rows: dict) -> dict:
    roles = {p.get("slug"): p.get("role") for p in rows.get("party") or []}
    out = {"parties": dict(Counter(r or "?" for r in roles.values())), "tables": {}}
    for name, d in defs.items():
        if not walks(d.get("client_scope")):
            continue
        per = Counter(client_of(name, r, defs, rows, roles) for r in rows.get(name) or [])
        out["tables"][name] = {"rows": sum(per.values()), "not_a_client": per.pop(None, 0),
                               "orphans": per.pop(ORPHAN, 0), "unstamped": per.pop(UNSTAMPED, 0),
                               "by_client": dict(per)}
    return out


def visibility_drift(defs: dict, live_vis: dict) -> list[str]:
    """Red lines for live tables whose grade is not the def's. None = table not created yet."""
    return [f"{n}: def says visibility {d.get('visibility')!r}, live table is {live_vis[n]!r}"
            for n, d in defs.items() if live_vis.get(n) and live_vis[n] != d.get("visibility")]


def _live_visibility(table: str, hdr: dict) -> str | None:
    from digest_absorb import AGENT, _open  # noqa: E402
    try:
        with _open(urllib.request.Request(f"{AGENT}/{table}", headers=hdr)) as r:
            body = json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    return (body.get("data") or body).get("visibility")


def read_live(defs: dict) -> dict:
    sys.path.insert(0, str(REPO / "tools"))
    from digest_absorb import proxy_header, read_rows, ro_token  # noqa: E402
    need = {"party"} | {n for n, d in defs.items() if walks(d.get("client_scope"))}
    hdr = {"Authorization": f"Bearer {ro_token()}", **proxy_header()}
    rows = {t: read_rows(t, hdr) for t in sorted(need)}
    rows["_visibility"] = {n: _live_visibility(n, hdr) for n in sorted(defs)}
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description="whose data each KEAP table holds")
    ap.add_argument("--rows-json", help="{table: [rows]} instead of live KEAP")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    try:
        defs = load_defs()
    except (OSError, yaml.YAMLError) as exc:
        print(f"septum: UNKNOWN — cannot read state/keap-tables ({exc})")
        return 0
    red, warn = declarations(defs)
    try:
        rows = (json.loads(Path(a.rows_json).read_text(encoding="utf-8")) if a.rows_json
                else read_live(defs))
        vis = rows.pop("_visibility", None)
        state, why = live(defs, rows), None
    except Exception as exc:  # any failure to read KEAP is UNKNOWN, never green
        state, vis, why = None, None, f"{type(exc).__name__}: {exc}"
    red += visibility_drift(defs, vis or {})
    warn += [f"{n}: {t['unstamped']} unstamped rows — no book_owner on their path"
             for n, t in sorted((state or {}).get("tables", {}).items()) if t["unstamped"]]
    red += [f"{n}: {t['orphans']} orphan rows — a ref points at a row that is gone"
            for n, t in sorted((state or {}).get("tables", {}).items()) if t["orphans"]]
    verdict = "RED" if red else ("UNKNOWN" if state is None or vis is None else "OK")
    if a.json:
        print(json.dumps({"verdict": verdict, "red": red, "warn": warn, "live": state,
                          "live_visibility": vis,
                          "live_unknown": why, "scopes": {n: d.get("client_scope") for n, d in defs.items()}},
                         indent=2, ensure_ascii=False))
        return 0
    print(f"septum: {verdict} — {len(defs)} table defs, {len(red)} red, {len(warn)} warn "
          "(declaration only: KEAP isolates no rows yet)")
    for line in red:
        print(f"  red:  {line}")
    for line in warn:
        print(f"  warn: {line}")
    if vis is None:
        print("  visibility: UNKNOWN — live table grades not read")
    if state is None:
        print(f"  live: UNKNOWN — KEAP rows unreadable ({why})")
        return 0
    print("  parties: " + (", ".join(f"{k} {v}" for k, v in sorted(state["parties"].items())) or "none"))
    for name, t in sorted(state["tables"].items()):
        by = ", ".join(f"{k} {v}" for k, v in sorted(t["by_client"].items())) or "—"
        print(f"  {name:<24} {t['rows']:>5} rows  clients: {by}  not a client's: {t['not_a_client']}  "
              f"orphans: {t['orphans']}  unstamped: {t['unstamped']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
