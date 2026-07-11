#!/usr/bin/env python3
"""keap-consolidate — the cortex consolidator (the "dream" sweep).

Pulse job (keap-base). The human-sleep analogy: while the operator rests,
this job walks the RAW data piles that landed in nOS during the day —
Nextcloud user files, the ~/keap/inbox drop dir, operator-imported MariaDB
databases — and registers every new/changed item as a KEAP DATAPOINT
through the unified intake (/ingest/v1/capture, capture-tier token). The
downstream night shift then makes them knowledge: keap-embed-sync gives
them vectors (semantic findability), keap-lint candidates duplicates and
deserts, and the librarian judges. Consolidation NEVER writes the curated
layer — datapoints land in the review queue like every other capture.

Sources (all optional; a missing source is skipped silently):
  filesystem  NOS_CONSOLIDATE_FS_ROOTS   colon-separated roots. Two shapes:
                <dir>            — walked recursively (the ~/keap/inbox drop dir)
                <dir>/*/files    — Nextcloud data layout (per-user files/)
              Small text files (.md .txt ≤64 KiB) ship their content as the
              capture text so they embed meaningfully; binaries ship
              path+size metadata (content extraction = phase 2).
  mariadb     NOS_MARIADB_ROOT_PASSWORD + NOS_CONSOLIDATE_DB_EXCLUDE
              (comma list of provisioned service DBs). Anything OUTSIDE the
              exclude list is an operator-imported knowledge dump: one
              datapoint per table (columns summary + row count).

State: ~/.nos/keap-consolidate-state.json (signature per item; only
new/changed items POST). Idempotent capture ids = sha1 of the source key,
so re-captures UPDATE the same queue row instead of duplicating.

Env:
  KEAP_API_URL                default http://127.0.0.1:8091
  KEAP_AGENT_TOKEN_CAPTURE    required (write-only intake tier)
  NOS_CONSOLIDATE_FS_ROOTS    e.g. "$HOME/nextcloud-data:$HOME/keap/inbox"
  NOS_MARIADB_CONTAINER       default infra-mariadb-1
  NOS_MARIADB_ROOT_PASSWORD   empty = skip the SQL sweep
  NOS_CONSOLIDATE_DB_EXCLUDE  comma list (provisioned service DBs)
  NOS_CONSOLIDATE_MAX         per-run new-datapoint cap (default 200)
  NOS_NOTIFY_BIN              nos-notify.sh (batch summary; optional)

Exit: 0 swept (even 0 new), 1 config error, 2 KEAP unreachable.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

KEAP_API_URL = os.environ.get("KEAP_API_URL", "http://127.0.0.1:8091").rstrip("/")
TOKEN = os.environ.get("KEAP_AGENT_TOKEN_CAPTURE", "")
FS_ROOTS = [p for p in os.environ.get("NOS_CONSOLIDATE_FS_ROOTS", "").split(":") if p.strip()]
DB_CONTAINER = os.environ.get("NOS_MARIADB_CONTAINER", "infra-mariadb-1")
DB_PASSWORD = os.environ.get("NOS_MARIADB_ROOT_PASSWORD", "")
DB_EXCLUDE = {
    d.strip()
    for d in os.environ.get("NOS_CONSOLIDATE_DB_EXCLUDE", "").split(",")
    if d.strip()
} | {"mysql", "information_schema", "performance_schema", "sys"}
MAX_NEW = int(os.environ.get("NOS_CONSOLIDATE_MAX", "200"))
NOTIFY_BIN = os.environ.get("NOS_NOTIFY_BIN", "")
STATE_PATH = Path.home() / ".nos" / "keap-consolidate-state.json"

MEDIA_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".mp4", ".mov", ".mkv", ".mp3", ".wav", ".flac", ".ogg"}
TEXTUAL_EXT = {".md", ".txt", ".pdf", ".doc", ".docx", ".odt", ".rtf", ".csv", ".json", ".xml", ".html", ".epub"}
SKIP_NAMES = {".DS_Store", "Thumbs.db", "index.html", "nextcloud.log"}
INLINE_TEXT_EXT = {".md", ".txt"}
INLINE_TEXT_MAX = 64 * 1024


def sid(key: str) -> str:
    """Stable capture id for a source key — re-sweeps update, never duplicate."""
    return "dp-" + hashlib.sha1(key.encode()).hexdigest()[:24]


def post_capture(envelope: dict) -> None:
    req = urllib.request.Request(
        f"{KEAP_API_URL}/ingest/v1/capture",
        data=json.dumps(envelope).encode(),
        method="POST",
    )
    req.add_header("content-type", "application/json")
    req.add_header("authorization", f"Bearer {TOKEN}")
    with urllib.request.urlopen(req, timeout=30) as res:
        res.read()


def load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text())
    except (OSError, ValueError):
        return {}


# ── Filesystem sweep ──────────────────────────────────────────────────────────

def iter_fs_files():
    for root in FS_ROOTS:
        rootp = Path(os.path.expanduser(root))
        if not rootp.is_dir():
            continue
        # Nextcloud layout: <data>/<user>/files/** — sweep only user files,
        # never appdata/cache. A plain dir (the inbox) is walked whole.
        user_dirs = [d / "files" for d in rootp.iterdir() if (d / "files").is_dir()]
        for base in user_dirs or [rootp]:
            for path in base.rglob("*"):
                if not path.is_file() or path.name in SKIP_NAMES or path.name.startswith("."):
                    continue
                yield base, path


def sweep_fs(state: dict, budget: list[int]) -> int:
    new = 0
    fs_state = state.setdefault("fs", {})
    for base, path in iter_fs_files():
        if budget[0] <= 0:
            break
        try:
            st = path.stat()
        except OSError:
            continue
        key = str(path)
        signature = f"{int(st.st_mtime)}:{st.st_size}"
        if fs_state.get(key) == signature:
            continue
        ext = path.suffix.lower()
        modality = "media" if ext in MEDIA_EXT else "text"
        text = None
        if ext in INLINE_TEXT_EXT and st.st_size <= INLINE_TEXT_MAX:
            try:
                text = path.read_text(errors="replace")[:8000]
            except OSError:
                text = None
        rel = str(path.relative_to(base))
        post_capture({
            "id": sid(f"fs:{key}"),
            "source": {"kind": "app", "name": "consolidator"},
            "modality": modality,
            "title": path.name,
            "text": text or f"{rel} ({st.st_size} B)",
            "tags": ["consolidated", "fs"],
            "metadata": {
                "origin": "filesystem",
                "root": str(base),
                "path": rel,
                "size": st.st_size,
                "mtime": int(st.st_mtime),
                "ext": ext.lstrip("."),
            },
        })
        fs_state[key] = signature
        new += 1
        budget[0] -= 1
    return new


# ── MariaDB sweep (operator-imported knowledge dumps) ─────────────────────────

def mariadb_query(query: str) -> list[list[str]]:
    out = subprocess.run(
        ["docker", "exec", DB_CONTAINER, "mariadb", "-uroot", f"-p{DB_PASSWORD}",
         "-N", "--batch", "-e", query],
        capture_output=True, text=True, timeout=60,
    )
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip()[:200])
    return [line.split("\t") for line in out.stdout.splitlines() if line]


def sweep_mariadb(state: dict, budget: list[int]) -> int:
    if not DB_PASSWORD:
        return 0
    try:
        tables = mariadb_query(
            "SELECT table_schema, table_name, table_rows FROM information_schema.tables "
            "WHERE table_type='BASE TABLE'"
        )
    except (RuntimeError, subprocess.SubprocessError, FileNotFoundError) as exc:
        print(f"keap-consolidate: mariadb sweep skipped: {exc}", file=sys.stderr)
        return 0
    new = 0
    db_state = state.setdefault("mariadb", {})
    for schema, table, rows_s in tables:
        if schema in DB_EXCLUDE or budget[0] <= 0:
            continue
        try:
            cols = mariadb_query(
                f"SELECT column_name, data_type FROM information_schema.columns "
                f"WHERE table_schema='{schema}' AND table_name='{table}' ORDER BY ordinal_position"
            )
        except RuntimeError:
            continue
        rows = int(rows_s or 0)
        col_sig = ",".join(f"{c}:{t}" for c, t in cols)
        # Row count enters the signature only by order of magnitude, so a
        # growing table doesn't re-capture every night.
        signature = hashlib.sha1(f"{col_sig}|{len(str(rows))}".encode()).hexdigest()[:16]
        key = f"{schema}.{table}"
        if db_state.get(key) == signature:
            continue
        post_capture({
            "id": sid(f"mariadb:{key}"),
            "source": {"kind": "app", "name": "consolidator"},
            "modality": "text",
            "title": f"SQL: {key}",
            "text": f"Imported table {key} (~{rows} rows). Columns: "
                    + "; ".join(f"{c} {t}" for c, t in cols[:40]),
            "tags": ["consolidated", "sql", schema],
            "metadata": {
                "origin": "mariadb",
                "database": schema,
                "table": table,
                "rows": rows,
                "columns": [{"name": c, "type": t} for c, t in cols[:100]],
            },
        })
        db_state[key] = signature
        new += 1
        budget[0] -= 1
    return new


def main() -> int:
    if not TOKEN:
        print("keap-consolidate: KEAP_AGENT_TOKEN_CAPTURE not set", file=sys.stderr)
        return 1
    try:
        req = urllib.request.Request(f"{KEAP_API_URL}/ingest/v1/health")
        urllib.request.urlopen(req, timeout=10).read()
    except (urllib.error.URLError, OSError) as exc:
        print(f"keap-consolidate: KEAP unreachable: {exc}", file=sys.stderr)
        return 2

    state = load_state()
    budget = [MAX_NEW]
    try:
        fs_new = sweep_fs(state, budget)
        db_new = sweep_mariadb(state, budget)
    finally:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(state))

    total = fs_new + db_new
    capped = " (cap reached — rest lands next run)" if budget[0] <= 0 else ""
    print(f"keap-consolidate: {total} new/changed datapoints (fs {fs_new}, sql {db_new}){capped}")
    if total >= 10 and NOTIFY_BIN and os.path.exists(NOTIFY_BIN):
        subprocess.run(
            [NOTIFY_BIN, "medium", "KEAP consolidator: data batch registered",
             f"{total} new datapoints queued for review (fs {fs_new}, sql {db_new}){capped}. "
             "They embed on the next keap-embed-sync run.",
             "wing-inbox"],
            check=False, timeout=30,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
