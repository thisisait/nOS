#!/usr/bin/env python3
"""Every KEAP DataTable out to a bundle before a blank, and back in after it.

The seed files carry only the git-owned half of a row; the table-owned half
(status, verified, occurred_at — what `nos dtt update` writes) lived only in
keap.db, which a blank wipes. The 10-09 and 10-17 blanks lost it for every table.

    keap-tables.py export [--dry-run|--confirm] [--since ISO]   # list / write a bundle
    keap-tables.py import [--dry-run|--confirm] [--since ISO] [--bundle DIR]

Dry run is the default and writes nothing. A bundle is a dir under
$KEAP_TABLES_BUNDLE_DIR (default ~/backups/staging/keap-tables): manifest.json +
one <table-id>.json per table (definition, rows, row history). KEAP has no
export/import route, so this walks the human door (/api/tables, paged rows,
/rows/<id>/history) as admin. Import recreates a table the fresh KEAP lacks
(same id; owner kept where a door allows it), adds bundle-only columns, and
upserts only the cells that differ — a re-run writes nothing. History is
archived, not replayed: the store only appends, it cannot be written back.
Exit: 0 ok, 2 KEAP unreachable / a write failed, 3 refused (stale bundle).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import keap_api  # noqa: E402

HOME = os.path.expanduser("~")
BUNDLE_DIR = os.environ.get("KEAP_TABLES_BUNDLE_DIR") or os.path.join(HOME, "backups", "staging", "keap-tables")
BLANK_RECORD = os.path.join(HOME, ".nos", "blank-runs.jsonl")
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
# The blank's record is stamped AFTER the wipe, minutes after the export ran.
# ponytail: fixed 1h window; the playbook passes --since and never relies on it.
RECORD_LAG = dt.timedelta(hours=1)


class Unreachable(Exception):
    pass


def call(method, path, body=None, user="akadmin", agent=False):
    if agent:
        url = f"{keap_api.agent_base()}{path}"
        hdr = {"authorization": f"Bearer {keap_api.agent_token_rw()}", "content-type": "application/json"}
    else:
        url = f"{keap_api.human_base()}{path}"
        hdr = keap_api.human_headers(username=user)
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=hdr, method=method),
                                    timeout=60) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {}
    except (urllib.error.URLError, OSError) as e:
        raise Unreachable(f"KEAP unreachable at {url}: {getattr(e, 'reason', e)}") from None


def get(path):
    st, d = call("GET", path)
    if st != 200:
        raise RuntimeError(f"GET {path} -> {st}: {d.get('error', d)}")
    return d


def q(s):
    return urllib.parse.quote(str(s), safe="")


def rows_of(tid):
    return keap_api.paged(get, f"/api/tables/{q(tid)}/rows")["data"]["rows"]


def now():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse(ts):
    return dt.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)


# ── export ───────────────────────────────────────────────────────────────────
def export(confirm, since):
    tables = get("/api/tables")["data"]
    print(f"KEAP DataTables at {keap_api.human_base()}: {len(tables)} tables")
    total = 0
    for t in tables:
        print(f"  {t['id']:40} {t.get('rowCount', '?'):>5} rows  {t.get('title', '')[:40]}")
        total += t.get("rowCount") or 0
    print(f"  total {total} rows")
    if not confirm:
        print(f"DRY RUN — nothing written; --confirm writes a bundle under {BUNDLE_DIR}")
        return 0
    stamp = now()
    final = os.path.join(BUNDLE_DIR, stamp.replace(":", ""))
    part = final + ".part"
    os.makedirs(part, mode=0o700, exist_ok=True)
    os.chmod(BUNDLE_DIR, 0o700)
    manifest = {"exported_at": stamp, "since": since, "source": keap_api.human_base(), "tables": []}
    for t in tables:
        tid = t["id"]
        info = get(f"/api/tables/{q(tid)}")["data"]   # carries the view block /api/tables omits
        rows = rows_of(tid)
        history = {}
        if (info.get("capabilities") or {}).get("rowHistory"):
            for r in rows:
                history[r["id"]] = get(f"/api/tables/{q(tid)}/rows/{q(r['id'])}/history?limit=200")["data"]
        path = os.path.join(part, f"{tid}.json")
        with open(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as fh:
            json.dump({"table": info, "rows": rows, "history": history}, fh, ensure_ascii=False)
        manifest["tables"].append({"id": tid, "rows": len(rows)})
    with open(os.open(os.path.join(part, "manifest.json"), os.O_WRONLY | os.O_CREAT, 0o600), "w") as fh:
        json.dump(manifest, fh, indent=1)
    os.rename(part, final)   # a half-written bundle never looks like a bundle
    print(f"WROTE {final} ({len(tables)} tables, {sum(x['rows'] for x in manifest['tables'])} rows)")
    return 0


# ── import ───────────────────────────────────────────────────────────────────
def newest_bundle():
    try:
        dirs = sorted(d for d in os.listdir(BUNDLE_DIR)
                      if not d.endswith(".part") and os.path.isfile(os.path.join(BUNDLE_DIR, d, "manifest.json")))
    except FileNotFoundError:
        dirs = []
    return os.path.join(BUNDLE_DIR, dirs[-1]) if dirs else None


def last_blank_start():
    try:
        with open(BLANK_RECORD) as fh:
            starts = [json.loads(line).get("started") for line in fh if line.strip()]
    except (OSError, ValueError):
        return None
    starts = [s for s in starts if s]
    return max(starts) if starts else None


def stale_reason(manifest, since):
    """Why this bundle must not be applied, or None. Older than its blank = an
    earlier blank's statuses would overwrite everything written since."""
    exported = parse(manifest["exported_at"])
    if since:
        if exported < parse(since):
            return f"bundle exported {manifest['exported_at']}, before this blank began ({since})"
        return None
    last = last_blank_start()
    if last and exported < parse(last) - RECORD_LAG:
        return (f"bundle exported {manifest['exported_at']}, older than the last blank ({last}); "
                "pass --since <its export time> to apply it anyway")
    return None


def create_table(info):
    tid, owner = info["id"], info.get("ownerId") or "nos-agent"
    cols = info["schema"]["columns"]
    common = {k: info[k] for k in ("title", "description", "driver", "visibility", "sharedWith", "view")
              if info.get(k) not in (None, "")}
    if tid == f"todos-{owner}":
        st, d = call("GET", "/api/todos-table", user=owner)            # KEAP's own ensure, as the owner
    elif UUID.match(tid) and owner != "nos-agent":
        st, d = call("POST", "/api/tables", {"id": tid, **common, "schema": {"columns": cols}}, user=owner)
    else:
        st, d = call("POST", "/agent/v1/tables", {"slug": tid, **common, "columns": cols}, agent=True)
        if st == 200 and owner != "nos-agent":
            print(f"    note: {tid} recreated owned by nos-agent (was {owner}); no door keeps that owner")
    if st != 200:
        raise RuntimeError(f"create {tid} -> {st}: {d.get('error', d)}")
    return d["data"]


def add_columns(live, info):
    have = {c["key"] for c in live["schema"]["columns"]}
    extra = [c for c in info["schema"]["columns"] if c["key"] not in have]
    if extra:   # reconcile is additive-only, so the union is always accepted or 409s loudly
        st, d = call("POST", "/agent/v1/tables",
                     {"slug": live["id"], "columns": live["schema"]["columns"] + extra}, agent=True)
        if st != 200:
            raise RuntimeError(f"add columns {[c['key'] for c in extra]} to {live['id']} -> {st}: {d.get('error', d)}")
    return [c["key"] for c in extra]


def delta(row, live_row):
    """The cells (and row sharing) the live row lacks. Empty = nothing to write."""
    lv = (live_row or {}).get("values") or {}
    out = {k: v for k, v in (row.get("values") or {}).items() if lv.get(k) != v}
    sh, lsh = row.get("sharing") or {}, (live_row or {}).get("sharing") or {}
    for key, meta in (("visibility", "__visibility"), ("sharedWith", "__shared_with")):
        if sh.get(key) is not None and sh.get(key) != lsh.get(key):
            out[meta] = sh[key]
    return out


def import_(bundle, confirm, since):
    bundle = bundle or newest_bundle()
    if not bundle:
        print(f"no bundle under {BUNDLE_DIR} — nothing to import")
        return 0
    with open(os.path.join(bundle, "manifest.json")) as fh:
        manifest = json.load(fh)
    why = stale_reason(manifest, since)
    if why:
        print(f"REFUSING {bundle}: {why}")
        return 3
    live_ids = {t["id"] for t in get("/api/tables")["data"]}
    print(f"bundle {bundle} ({manifest['exported_at']}, {len(manifest['tables'])} tables) -> {keap_api.human_base()}")
    failed = written = 0
    for entry in manifest["tables"]:
        with open(os.path.join(bundle, f"{entry['id']}.json")) as fh:
            data = json.load(fh)
        info, tid = data["table"], data["table"]["id"]
        if tid not in live_ids:
            if not confirm:
                print(f"  {tid:40} CREATE + {len(data['rows'])} rows")
                continue
            live = create_table(info)
        else:
            live = get(f"/api/tables/{q(tid)}")["data"]
        if confirm:
            extra = add_columns(live, info)
        else:
            have = {c["key"] for c in live["schema"]["columns"]}
            extra = [c["key"] for c in info["schema"]["columns"] if c["key"] not in have]
        live_rows = {r["id"]: r for r in rows_of(tid)}
        todo = [(r, d) for r in data["rows"] if (d := delta(r, live_rows.get(r["id"])))]
        cols = f" (+columns {extra})" if extra else ""
        print(f"  {tid:40} {'exists' if tid in live_ids else 'created'}{cols}: "
              f"{len(todo)} rows to write, {len(data['rows']) - len(todo)} unchanged")
        if not confirm:
            continue
        # rowRef cells may point at a row a later one in the list creates: retry
        # the refused ones until a pass makes no progress.
        while todo:
            left = []
            for r, d in todo:
                st, resp = call("POST", f"/api/tables/{q(tid)}/rows", {"id": r["id"], "values": d})
                if st != 200:
                    left.append((r, d, f"{st}: {resp.get('error', resp)}"))
                else:
                    written += 1
            if len(left) == len(todo):
                for r, _, err in left:
                    print(f"    FAILED {tid}/{r['id']}: {err}")
                failed += len(left)
                break
            todo = [(r, d) for r, d, _ in left]
    print("DRY RUN — nothing written; --confirm applies it" if not confirm
          else f"WROTE {written} rows, {failed} failed")
    return 2 if failed else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("verb", choices=["export", "import"])
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="the default: list, write nothing")
    mode.add_argument("--confirm", action="store_true", help="write the bundle / apply it")
    ap.add_argument("--since", help="ISO-8601 UTC start of the blank this bundle belongs to")
    ap.add_argument("--bundle", help="import this bundle dir (default: the newest)")
    a = ap.parse_args(argv)
    try:
        if a.verb == "export":
            return export(a.confirm, a.since)
        return import_(a.bundle, a.confirm, a.since)
    except Unreachable as e:
        print(f"UNKNOWN: {e}")
        return 2
    except RuntimeError as e:
        print(f"FAILED: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
