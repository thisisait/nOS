"""Bone user-state — per-user structured KV store for nOS face apps.

The organ for "smaller structured data": UI personalization, app config, and the
state of face-native utils (sticky notes, desktop layout, favorite folders, an
explorer index, …). One embedded SQL DB per user, filed class-3 in the doctrine
tree so it is portable, backup-friendly, and per-user isolated:

    {NOS_DATA_ROOT}/tenants/{NOS_TENANT_SLUG}/users/{uid}/.face/state.db

`.face/` sits OUTSIDE the fs-sync classes (documents/library/inbox/nOS), so KEAP
never ingests app state as knowledge.

This is the SIMPLEST nos-app recipe (Tier F1, docs/doctrine/face-app-tiers.md):
a static UI + a namespaced KV/JSON store, no dedicated DB/schema/migrations.

Data model: rows of (namespace, key, JSON value). Namespaces partition apps
(`face.desktop`, `app.sticky-notes`, …). The value is arbitrary JSON.

Security mirrors the VFS: static-bearer auth (BONE_VFS_TOKEN — the face↔Bone
token), the caller-supplied uid pinned by the trusted face BFF, and the uid
validated so it can only address its own DB file.

Encryption (roadmap): swap `_connect()` to a SQLCipher/libSQL connection keyed
by a per-user secret from Infisical. The schema + API are unchanged — only the
connection factory. Kept unencrypted-at-rest for the walking skeleton.
"""

from __future__ import annotations

import hmac
import json
import os
import re
import sqlite3
import time
from pathlib import Path

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query

router = APIRouter(prefix="/api/v1/userstate", tags=["userstate"])

_NS_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_MAX_VALUE_BYTES = 256 * 1024  # a KV value is small structured data, not a blob


def _data_root() -> Path:
    return Path(os.environ.get("NOS_DATA_ROOT", str(Path.home() / "nos")))


def _tenant_slug() -> str:
    return os.environ.get("NOS_TENANT_SLUG", "pazny")


def require_face_token(authorization: str = Header(None)) -> None:
    """Same static-bearer gate as the VFS (BONE_VFS_TOKEN = the face↔Bone token)."""
    token = os.environ.get("BONE_VFS_TOKEN", "")
    if not token:
        raise HTTPException(status_code=503, detail="user-state not configured (BONE_VFS_TOKEN unset)")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization: Bearer <token> required")
    provided = authorization.split(" ", 1)[1].strip()
    if not hmac.compare_digest(provided, token):
        raise HTTPException(status_code=403, detail="invalid token")


def _validate_uid(uid: str) -> str:
    if not uid or "/" in uid or uid in (".", "..") or uid.startswith("."):
        raise HTTPException(status_code=400, detail="invalid uid")
    return uid


def _db_path(uid: str) -> Path:
    root = (_data_root() / "tenants" / _tenant_slug() / "users" / _validate_uid(uid)).resolve()
    face_dir = root / ".face"
    face_dir.mkdir(parents=True, exist_ok=True)
    try:
        face_dir.chmod(0o700)
    except OSError:
        pass  # macOS single-user: structural only
    return face_dir / "state.db"


def _connect(uid: str) -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path(uid)))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS kv (
               namespace TEXT NOT NULL,
               key       TEXT NOT NULL,
               value     TEXT NOT NULL,
               updated_at INTEGER NOT NULL,
               PRIMARY KEY (namespace, key)
           )"""
    )
    return conn


def _ns(ns: str) -> str:
    if not _NS_RE.match(ns or ""):
        raise HTTPException(status_code=400, detail="invalid namespace")
    return ns


def _key(key: str) -> str:
    if not _KEY_RE.match(key or ""):
        raise HTTPException(status_code=400, detail="invalid key")
    return key


# ── Read ─────────────────────────────────────────────────────────────────────

@router.get("/get")
def us_get(
    uid: str = Query(...),
    ns: str = Query(...),
    key: str = Query(...),
    _=Depends(require_face_token),
) -> dict:
    _ns(ns)
    _key(key)
    conn = _connect(uid)
    try:
        row = conn.execute(
            "SELECT value, updated_at FROM kv WHERE namespace=? AND key=?", (ns, key)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    return {"ns": ns, "key": key, "value": json.loads(row[0]), "updated_at": row[1]}


@router.get("/list")
def us_list(uid: str = Query(...), ns: str = Query(...), _=Depends(require_face_token)) -> dict:
    _ns(ns)
    conn = _connect(uid)
    try:
        rows = conn.execute(
            "SELECT key, value, updated_at FROM kv WHERE namespace=? ORDER BY key", (ns,)
        ).fetchall()
    finally:
        conn.close()
    return {
        "ns": ns,
        "items": [{"key": k, "value": json.loads(v), "updated_at": u} for (k, v, u) in rows],
    }


# ── Write ────────────────────────────────────────────────────────────────────

@router.post("/set")
def us_set(body: dict = Body(...), _=Depends(require_face_token)) -> dict:
    uid = body.get("uid", "")
    ns = _ns(body.get("ns", ""))
    key = _key(body.get("key", ""))
    if "value" not in body:
        raise HTTPException(status_code=400, detail="value is required")
    value = json.dumps(body["value"], separators=(",", ":"))
    if len(value.encode("utf-8")) > _MAX_VALUE_BYTES:
        raise HTTPException(status_code=413, detail="value too large")
    conn = _connect(uid)
    try:
        conn.execute(
            "INSERT INTO kv(namespace,key,value,updated_at) VALUES(?,?,?,?) "
            "ON CONFLICT(namespace,key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (ns, key, value, int(time.time())),
        )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "ns": ns, "key": key}


@router.post("/delete")
def us_delete(body: dict = Body(...), _=Depends(require_face_token)) -> dict:
    uid = body.get("uid", "")
    ns = _ns(body.get("ns", ""))
    key = _key(body.get("key", ""))
    conn = _connect(uid)
    try:
        cur = conn.execute("DELETE FROM kv WHERE namespace=? AND key=?", (ns, key))
        conn.commit()
        deleted = cur.rowcount
    finally:
        conn.close()
    return {"ok": True, "deleted": deleted}
