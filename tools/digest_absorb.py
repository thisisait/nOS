"""Shared absorb for digest importers — the one place a gated bundle's rows reach
the live door, reused by every importer CLI (digest-import.py, digest-import-repos.py).

The second importer is what justified extracting this from digest-import.py: absorb
semantics (strip _prov, upsert by slug in dependency order, skip slugs already
present so a re-run is a no-op) are identical across importers and must not drift.
THIS is the importer-surface chokepoint: absorb() runs check_bundle and POSTs
/rows only when the gate is empty. CLIs still gate first; a caller that skips
that and hands absorb an ungated bundle is refused here. Other DataTable writers
(roadmap, MCP) are out of scope — raw-never-touches-knowledge still needs
raw-archive + captures/proposals validators before that constitution rule flips.
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

#: A KEAP call's deadline. Not a constant because the host budget is not one:
#: with a 14B model resident the API answers in ~25s instead of ~0.1s
#: (measured), and a flat 15s made every digest tool fail while the vision
#: pipeline's own model was still warm — the sweep that had JUST extracted a
#: document could not file it.
_TIMEOUT_S = float(os.environ.get("NOS_KEAP_TIMEOUT_S", "15"))


def _open(req, timeout: float | None = None):
    """urlopen with ONE retry at a doubled deadline. Slow is not down: the
    retry rescues a loaded host, and a genuinely unreachable KEAP still raises
    — the caller's refusal is unchanged."""
    first = timeout or _TIMEOUT_S
    try:
        return urllib.request.urlopen(req, timeout=first)
    except TimeoutError:
        return urllib.request.urlopen(req, timeout=first * 2)



def rw_token() -> str:
    tok = os.environ.get("KEAP_AGENT_TOKEN_RW", "").strip()
    if tok:
        return tok
    try:
        return subprocess.run(["docker", "exec", "iiab-keap-1", "printenv", "KEAP_AGENT_TOKEN_RW"],
                              capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def ro_token() -> str:
    tok = os.environ.get("KEAP_AGENT_TOKEN_RO", "").strip()
    if tok:
        return tok
    try:
        return subprocess.run(["docker", "exec", "iiab-keap-1", "printenv", "KEAP_AGENT_TOKEN_RO"],
                              capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _rows_from_envelope(data: dict) -> list:
    """Rows out of a KEAP list response. They nest under `data` ({success, data:{
    rows:[...]}}); reading top-level `rows` on that shape returns [] and made absorb
    re-post every existing row as a false "wrote". Reads either shape. Pure → tested."""
    return (data.get("data") or {}).get("rows") or data.get("rows") or []


def read_rows(table: str, hdr: dict | None = None) -> list:
    """Every row of a table (RO). 404 → [] (a table this estate lacks is silent)."""
    hdr = hdr or {"Authorization": f"Bearer {ro_token()}", **proxy_header()}
    req = urllib.request.Request(f"{AGENT}/{table}/rows", headers=hdr)
    try:
        with _open(req) as r:
            return _rows_from_envelope(json.loads(r.read() or b"{}"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return []
        raise


def build_party_index() -> dict:
    """{by_key: {(scheme, value): party_slug}, by_name: {normname: [slug]}} for
    resolve_party — party-tax-identity ⋈ party over the live spine. Shared by
    every importer that resolves counterparties (repos, isdoc, …)."""
    hdr = {"Authorization": f"Bearer {ro_token()}", **proxy_header()}
    by_key, by_name = {}, {}
    for t in read_rows("party-tax-identity", hdr):
        if t.get("scheme") and t.get("value") and t.get("party"):
            by_key[(t["scheme"], str(t["value"]))] = t["party"]
    for p in read_rows("party", hdr):
        nm = nos_digest.normalize_org_name(p.get("legal_name") or "")
        if nm:
            by_name.setdefault(nm, []).append(p["slug"])
    return {"by_key": by_key, "by_name": by_name}


def _existing_slugs(table: str, hdr: dict) -> set:
    return {row.get("slug") for row in read_rows(table, hdr)}


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
    if d.get("graph") is not None:      # row projection (keap v1.47.0) — same forward law as view
        body["graph"] = d["graph"]
    req = urllib.request.Request(AGENT, method="POST",
                                 headers={**hdr, "content-type": "application/json"},
                                 data=json.dumps(body).encode("utf-8"))
    try:
        with _open(req):
            pass
    except urllib.error.HTTPError as e:
        if e.code == 409:
            raise SystemExit(f"KEAP refused {table} schema (409): a column drop/kind change "
                             f"the def asks for conflicts with existing rows — {e.read().decode()[:160]}")
        raw = e.read().decode()
        # Live KEAP 2.0.0-rc.1 still refuses rowRef facets; face's contract already
        # allows them (book_owner / party). Drop view AND graph so COLUMNS still
        # land — a 400 here used to abort the whole absorb as "KEAP unreadable",
        # and pending-invoice-verify ships graph (no view), so dropping view alone
        # never retried that table.
        if e.code == 400 and "facets" in raw and (body.get("view") or body.get("graph")):
            body.pop("view", None)
            body.pop("graph", None)
            req2 = urllib.request.Request(AGENT, method="POST",
                                          headers={**hdr, "content-type": "application/json"},
                                          data=json.dumps(body).encode("utf-8"))
            try:
                with _open(req2):
                    return
            except urllib.error.HTTPError as e2:
                if e2.code != 404:
                    raise
                return
        if e.code != 404:   # 404 = agent route absent; rows POST will report it
            raise


def _post_row(table: str, row: dict, hdr: dict) -> None:
    body = {k: v for k, v in row.items() if not str(k).startswith("__")}
    req = urllib.request.Request(f"{AGENT}/{table}/rows", method="POST",
                                 headers={**hdr, "content-type": "application/json"},
                                 data=json.dumps(body).encode("utf-8"))
    with _open(req):
        pass


def absorb(bundle: dict) -> int:
    """Upsert a gated bundle's deterministic rows by slug, in dependency order,
    skipping slugs already present. Returns 0 done · 1 gate refused or a POST
    failed · 2 KEAP unreadable. _prov is stripped here — it is never a table
    column. Ungated bundles never reach the live row POST."""
    errors = nos_digest.check_bundle(bundle, TABLES_DIR)
    if errors:
        print("GATE REFUSED the bundle — nothing absorbed:", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        return 1
    hdr = {"Authorization": f"Bearer {rw_token()}", **proxy_header()}
    det = nos_digest.strip_provenance(bundle["deterministic"])
    wrote = skipped = 0
    for table, rows in det.items():   # dict preserves dependency order
        try:
            ensure_table(table, hdr)
            present = _existing_slugs(table, hdr)
        except urllib.error.HTTPError as exc:
            print(f"REFUSING: {table} schema HTTP {exc.code}", file=sys.stderr)
            return 1
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
