#!/usr/bin/env python3
"""Offboard one client FIRM's books (book_owner slug).

Parallel to email-keyed tasks/gdpr-forget.yml: dry-run by default, prints an
audited plan, mutates nothing unless --confirm equals the slug (or
NOS_OFFBOARD_CONFIRM does). A typo cannot wipe Alfa while naming Beta.

Confirm rmtree's the inbox (outside this git checkout) and DELETEs planned
KEAP rows via keap_api.delete_row (human door; agent v1 has no row DELETE).
Espo Account DELETE stays operator-run. Trained-model Art-17 is unsolved.

  tools/offboard-book-owner.py synthetic-client-alfa
  tools/offboard-book-owner.py synthetic-client-alfa --confirm synthetic-client-alfa
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import shutil
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
MAP = REPO / "state" / "offboard-book-owner.yml"
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
LEAVES = ("incoming", "extracts", "processed")
ESPO_MARKER = "nos:party:"
KEAP_DELETE = "/api/tables/{table}/rows/{slug}"


def slug_ok(slug: str) -> bool:
    return bool(SLUG_RE.fullmatch(slug or ""))


def load_map(path: pathlib.Path = MAP) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def confirm_token(confirm_arg: str | None, env: str | None) -> str | None:
    """None = dry-run. Any supplied token that is not the slug refuses later."""
    tokens = [t for t in (confirm_arg, env) if t]
    if not tokens:
        return None
    return tokens[0] if len(set(tokens)) == 1 else "__mismatch__"


def _codes_311_321(code: str) -> bool:
    c = str(code or "")
    return c.startswith("311") or c.startswith("321")


def _invoice_slugs(rows: dict, owner: str) -> set[str]:
    return {r["slug"] for r in rows.get("invoice") or []
            if isinstance(r, dict) and r.get("book_owner") == owner and r.get("slug")}


def _je_slugs(rows: dict, invoices: set[str]) -> set[str]:
    return {r["slug"] for r in rows.get("journal-entry") or []
            if isinstance(r, dict) and r.get("source") in invoices and r.get("slug")}


def _extract_names(fs_dirs: list[pathlib.Path]) -> set[str]:
    names: set[str] = set()
    for d in fs_dirs:
        if d.name != "extracts" or not d.is_dir():
            continue
        names.update(p.name for p in d.iterdir() if p.is_file())
    return names


def _pending_hit(row: dict, owner: str, extracts: set[str]) -> bool:
    sid = str(row.get("sidecar_id") or "")
    if sid and sid in extracts:
        return True
    blob = json.dumps(row.get("fields") or {}, default=str)
    return owner in blob or owner in sid or row.get("book_owner") == owner


def _match_rows(table: str, match: str, owner: str, rows: dict,
                invoices: set[str], journals: set[str],
                extracts: set[str], accounts: set[str]) -> list[str]:
    bucket = [r for r in (rows.get(table) or []) if isinstance(r, dict) and r.get("slug")]
    if match == "book_owner":
        return [r["slug"] for r in bucket if r.get("book_owner") == owner]
    if match == "source_invoice":
        return [r["slug"] for r in bucket if r.get("source") in invoices]
    if match == "parent_invoice":
        return [r["slug"] for r in bucket if r.get("invoice") in invoices]
    if match == "posting_for_owner":
        return [r["slug"] for r in bucket
                if r.get("entry") in journals or r.get("account") in accounts]
    if match == "sidecar_or_fields":
        return [r["slug"] for r in bucket if _pending_hit(r, owner, extracts)]
    if match == "party":
        return [r["slug"] for r in bucket if r.get("party") == owner]
    if match == "analytical_311_321":
        return [r["slug"] for r in bucket
                if r.get("party") == owner and _codes_311_321(r.get("code"))]
    if match == "slug":
        return [r["slug"] for r in bucket if r["slug"] == owner]
    return []


def _remaining_refs(owner: str, rows: dict, deleting: set[tuple[str, str]]) -> bool:
    for table, bucket in rows.items():
        for r in bucket or []:
            if not isinstance(r, dict) or not r.get("slug"):
                continue
            if (table, r["slug"]) in deleting:
                continue
            if any(v == owner for v in r.values()):
                return True
    return False


def is_git_fixture(path: pathlib.Path, repo: pathlib.Path = REPO) -> bool:
    """Never rmtree anything inside the checkout (state/fixtures, tools, …)."""
    try:
        path.resolve().relative_to(repo.resolve())
        return True
    except ValueError:
        return False


def scan_inbox(data_root: pathlib.Path | None, owner: str) -> list[pathlib.Path]:
    if not data_root:
        return []
    found: list[pathlib.Path] = []
    for tenant in (data_root / "tenants").glob("*"):
        for user in (tenant / "users").glob("*"):
            base = user / "inbox" / "accounting" / owner
            for leaf in LEAVES:
                p = base / leaf
                if p.is_dir():
                    found.append(p)
    return found


def audit_body(owner: str, dry: bool) -> dict:
    return {
        "type": "gdpr.dsar",
        "request_type": "erase",
        "status": "received" if dry else "in-progress",
        "subject": owner,
        "notes": ("Dry-run: book_owner offboard plan logged, no deletion."
                  if dry else "Confirmed: filesystem rmtree + KEAP DELETE; Espo remains manual."),
        "source": "offboard-book-owner",
    }


def plan(owner: str, rows: dict, data_root: pathlib.Path | None = None,
         repo: pathlib.Path = REPO, spec: dict | None = None) -> dict:
    spec = spec or load_map()
    invoices = _invoice_slugs(rows, owner)
    journals = _je_slugs(rows, invoices)
    accounts = {r["slug"] for r in rows.get("account") or []
                if isinstance(r, dict) and r.get("party") == owner
                and _codes_311_321(r.get("code")) and r.get("slug")}
    fs_all = scan_inbox(data_root, owner)
    fs_ok = [p for p in fs_all if not is_git_fixture(p, repo)]
    fs_skip = [p for p in fs_all if is_git_fixture(p, repo)]
    extracts = _extract_names(fs_ok)

    keap: list[dict] = []
    deleting: set[tuple[str, str]] = set()
    for step in spec.get("keap_delete_order") or []:
        table, match = step["table"], step["match"]
        slugs = _match_rows(table, match, owner, rows, invoices, journals, extracts, accounts)
        if step.get("last") and _remaining_refs(owner, rows, deleting | {(table, s) for s in slugs}):
            keap.append({"table": table, "slug": owner, "action": "retain",
                         "reason": "other rows still reference this party (not this book's alone)"})
            continue
        for s in slugs:
            deleting.add((table, s))
            keap.append({"table": table, "slug": s, "method": "DELETE",
                         "path": KEAP_DELETE.format(table=table, slug=s)})

    espo = spec.get("espo") or {}
    marker = ESPO_MARKER + owner
    return {
        "slug": owner,
        "keap": keap,
        "filesystem": [{"action": "rmtree", "path": str(p)} for p in fs_ok],
        "filesystem_skipped_git": [str(p) for p in fs_skip],
        "espo": {"method": espo.get("method", "manual"), "marker": marker,
                 "note": (espo.get("note") or "").replace("<slug>", owner)},
        "audit_post": {"url": "http://127.0.0.1:8099/api/v1/events",
                       "body": audit_body(owner, dry=True)},
        "unsolved": ["trained-model Art-17 (embeddings) unsolved"],
    }


def delete_row(table: str, slug: str) -> None:
    """Human-door DELETE. Tests monkeypatch this — never hit live KEAP in pytest."""
    sys.path.insert(0, str(REPO / "tools"))
    import keap_api  # noqa: E402
    keap_api.delete_row(table, slug)


def execute_keap(planned: dict) -> list[tuple[str, str]]:
    done = []
    for step in planned.get("keap") or []:
        if step.get("method") != "DELETE":
            continue
        delete_row(step["table"], step["slug"])
        done.append((step["table"], step["slug"]))
    return done


def load_live_rows(spec: dict | None = None) -> dict:
    spec = spec or load_map()
    sys.path.insert(0, str(REPO / "tools"))
    from digest_absorb import read_rows  # noqa: E402
    out: dict = {}
    tables = [s["table"] for s in (spec.get("keap_delete_order") or [])]
    for table in tables:
        try:
            out[table] = read_rows(table)
        except Exception:
            out[table] = []
    return out


def apply_fs(planned: dict, repo: pathlib.Path = REPO) -> list[str]:
    removed = []
    for item in planned.get("filesystem") or []:
        p = pathlib.Path(item["path"])
        if is_git_fixture(p, repo):
            continue
        if p.is_dir():
            shutil.rmtree(p)
            removed.append(str(p))
    return removed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("slug", help="book_owner party slug")
    ap.add_argument("--confirm", metavar="SLUG", default=None,
                    help="must equal the slug (typo gate)")
    ap.add_argument("--data-root", default=None)
    ap.add_argument("--rows-json", default=None,
                    help="fake/injected {table: [rows]} — never hits live KEAP")
    args = ap.parse_args(argv)

    if not slug_ok(args.slug):
        print(f"REFUSING: slug {args.slug!r} does not match {SLUG_RE.pattern}", file=sys.stderr)
        return 2

    env = os.environ.get("NOS_OFFBOARD_CONFIRM", "").strip() or None
    token = confirm_token(args.confirm, env)
    if token == "__mismatch__":
        print("REFUSING: --confirm and NOS_OFFBOARD_CONFIRM disagree", file=sys.stderr)
        return 2
    if token is not None and token != args.slug:
        print(f"REFUSING: confirm {token!r} is not slug {args.slug!r}", file=sys.stderr)
        return 2

    rows = {}
    if args.rows_json:
        rows = json.loads(pathlib.Path(args.rows_json).read_text(encoding="utf-8"))
    else:
        rows = load_live_rows()
    root = pathlib.Path(args.data_root) if args.data_root else None
    planned = plan(args.slug, rows, data_root=root)

    dry = token is None

    planned["mode"] = "DRY-RUN" if dry else "CONFIRM"
    planned["audit_post"]["body"] = audit_body(args.slug, dry=dry)
    json.dump(planned, sys.stdout, indent=2)
    sys.stdout.write("\n")
    if dry:
        return 0
    apply_fs(planned)
    try:
        execute_keap(planned)
    except Exception as exc:
        print(f"REFUSING: KEAP DELETE failed ({exc})", file=sys.stderr)
        return 1
    print("CONFIRM: filesystem rmtree + KEAP DELETE done; Espo remains manual.",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
