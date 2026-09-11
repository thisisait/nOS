"""Shared absorb for digest importers — the one place a gated bundle's rows reach
the live door, reused by every importer CLI (digest-import.py, digest-import-repos.py).

The second importer is what justified extracting this from digest-import.py: absorb
semantics (strip _prov, upsert by slug in dependency order, skip slugs already
present so a re-run is a no-op) are identical across importers and must not drift.
It is NOT the enforcement chokepoint (see the raw-never-touches-knowledge review) —
each CLI still runs run_importer/check_bundle and refuses on errors BEFORE calling
this; absorb assumes an already-gated bundle.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import urllib.error
import urllib.request

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "files" / "anatomy" / "module_utils"))
from keap_api import proxy_header  # noqa: E402
import nos_digest  # noqa: E402

AGENT = "http://127.0.0.1:8091/agent/v1/tables"
TABLES_DIR = REPO / "state" / "keap-tables"


def rw_token() -> str:
    tok = os.environ.get("KEAP_AGENT_TOKEN_RW", "").strip()
    if tok:
        return tok
    return subprocess.run(["docker", "exec", "iiab-keap-1", "printenv", "KEAP_AGENT_TOKEN_RW"],
                          capture_output=True, text=True).stdout.strip()


def _existing_slugs(table: str, hdr: dict) -> set:
    req = urllib.request.Request(f"{AGENT}/{table}/rows", headers=hdr)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read() or b"{}")
        # rows nest under `data` ({success, data:{rows:[...]}}); reading top-level
        # `rows` returns empty and re-posts every existing row (a false "wrote").
        rows = (data.get("data") or {}).get("rows") or data.get("rows") or []
        return {row.get("slug") for row in rows}
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return set()
        raise


def ensure_table(table: str, hdr: dict) -> None:
    """Reconcile the DataTable from its committed def before upserting rows — a
    digest importer owns its OUTPUT tables' existence (the party spine already
    exists; repo/application/package are created here). Mirrors seed-face-table's
    reconcile: additive/relabel is 200/201, a destructive schema change is 409
    (an authoring error, raised loud), a missing def means the table must already
    exist (the caller's rows will 404 loudly if not). Idempotent."""
    p = TABLES_DIR / f"{table}.table.yml"
    if not p.exists():
        return
    d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    body = {"slug": table, "title": d.get("title", table),
            "description": d.get("description", ""),
            "driver": d.get("driver", "libsql"),
            "visibility": d.get("visibility", "tier-managers"),
            "anchors": d.get("anchors", []),
            "columns": d["schema"]["columns"]}
    if d.get("sharedWith") is not None:
        body["sharedWith"] = d["sharedWith"]
    if d.get("view") is not None:
        body["view"] = d["view"]
    req = urllib.request.Request(AGENT, method="POST",
                                 headers={**hdr, "content-type": "application/json"},
                                 data=json.dumps(body).encode("utf-8"))
    try:
        with urllib.request.urlopen(req, timeout=15):
            pass
    except urllib.error.HTTPError as e:
        if e.code == 409:
            raise SystemExit(f"KEAP refused {table} schema (409): a column drop/kind change "
                             f"the def asks for conflicts with existing rows — {e.read().decode()[:160]}")
        if e.code != 404:   # 404 = agent route absent; rows POST will report it
            raise


def _post_row(table: str, row: dict, hdr: dict) -> None:
    req = urllib.request.Request(f"{AGENT}/{table}/rows", method="POST",
                                 headers={**hdr, "content-type": "application/json"},
                                 data=json.dumps(row).encode("utf-8"))
    with urllib.request.urlopen(req, timeout=15):
        pass


def absorb(bundle: dict) -> int:
    """Upsert a gated bundle's deterministic rows by slug, in dependency order,
    skipping slugs already present. Returns 0 done · 1 a POST failed · 2 KEAP
    unreadable. _prov is stripped here — it is never a table column."""
    hdr = {"Authorization": f"Bearer {rw_token()}", **proxy_header()}
    det = nos_digest.strip_provenance(bundle["deterministic"])
    wrote = skipped = 0
    for table, rows in det.items():   # dict preserves dependency order
        try:
            ensure_table(table, hdr)
            present = _existing_slugs(table, hdr)
        except (urllib.error.URLError, OSError) as exc:
            print(f"REFUSING: KEAP unreadable ({exc})", file=sys.stderr)
            return 2
        for row in rows:
            if row["slug"] in present:
                print(f"  · {table}/{row['slug']}: already present")
                skipped += 1
                continue
            try:
                _post_row(table, row, hdr)
                print(f"  + {table}/{row['slug']}")
                wrote += 1
            except urllib.error.HTTPError as e:
                print(f"  FAILED {table}/{row['slug']}: {e.code} {e.read().decode()[:160]}",
                      file=sys.stderr)
                return 1
    print(f"\nabsorbed {wrote} · already present {skipped}")
    return 0
