"""Bone VFS — real-file backend for nOS face over the class-3 per-user tree.

The one new backend behind the nOS face file browser + (M2b) file-picker service.
Bone is a HOST daemon, so it reaches the doctrine tree natively — no mount:

    {NOS_DATA_ROOT}/tenants/{NOS_TENANT_SLUG}/users/{uid}/{documents,library,inbox,agents,...}

Security model (two independent layers):
  1. The caller (the face BFF) authenticates with a static bearer = BONE_VFS_TOKEN
     (face_vfs_token). Bone binds loopback only, so only host processes reach it.
  2. Every path is resolved and asserted to live INSIDE the caller-supplied user
     root (realpath ∈ scope) — a `..`/symlink escape is refused with 403. The BFF
     pins `uid` from the edge-trusted Authentik identity; Bone trusts that uid only
     because the caller holds the VFS token (the keap-agent-token precedent).

macOS runs every process as one user, so class-3 0700 isolation is structural
there; the realpath-∈-scope check is what actually enforces the boundary and is
identical on Linux (where the 0700 UID split is also real).
"""

from __future__ import annotations

import hmac
import os
import shutil
from pathlib import Path

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse

router = APIRouter(prefix="/api/v1/vfs", tags=["vfs"])

# Caps — keep responses bounded (the browser is not a bulk-transfer tool).
_MAX_READ_BYTES = 5 * 1024 * 1024        # 5 MB inline text read
_MAX_UPLOAD_BYTES = 128 * 1024 * 1024    # 128 MB upload
_MAX_LIST_ENTRIES = 5000


def _data_root() -> Path:
    return Path(os.environ.get("NOS_DATA_ROOT", str(Path.home() / "nos")))


def _tenant_slug() -> str:
    return os.environ.get("NOS_TENANT_SLUG", "pazny")


def _vfs_token() -> str:
    return os.environ.get("BONE_VFS_TOKEN", "")


def require_vfs_token(authorization: str = Header(None)) -> None:
    """Static-bearer gate for the VFS. Distinct from Bone's JWT scopes because the
    face BFF holds forward-auth headers, not an Authentik token."""
    token = _vfs_token()
    if not token:
        raise HTTPException(status_code=503, detail="VFS not configured (BONE_VFS_TOKEN unset)")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization: Bearer <token> required")
    provided = authorization.split(" ", 1)[1].strip()
    if not hmac.compare_digest(provided, token):
        raise HTTPException(status_code=403, detail="invalid VFS token")


def _user_root(uid: str) -> Path:
    if not uid or "/" in uid or uid in (".", "..") or uid.startswith("."):
        raise HTTPException(status_code=400, detail="invalid uid")
    return (_data_root() / "tenants" / _tenant_slug() / "users" / uid).resolve()


def _resolve(uid: str, relpath: str, *, must_exist: bool = False) -> Path:
    """Resolve relpath under the user's root and REFUSE any escape (realpath ∈ scope)."""
    root = _user_root(uid)
    rel = (relpath or "").strip()
    if os.path.isabs(rel) or rel.startswith("\\"):
        raise HTTPException(status_code=400, detail="path must be relative")
    target = (root / rel).resolve()
    # Containment: target must be the root itself or strictly beneath it. Using
    # resolved (realpath) paths defeats `..` and symlink escapes.
    if target != root and root not in target.parents:
        raise HTTPException(status_code=403, detail="path escapes user scope")
    if must_exist and not target.exists():
        raise HTTPException(status_code=404, detail="not found")
    return target


def _rel(uid: str, p: Path) -> str:
    try:
        return str(p.relative_to(_user_root(uid)))
    except ValueError:
        return p.name


def _entry(uid: str, p: Path) -> dict:
    st = p.stat()
    return {
        "name": p.name,
        "path": _rel(uid, p),
        "kind": "dir" if p.is_dir() else "file",
        "size": 0 if p.is_dir() else st.st_size,
        "mtime": int(st.st_mtime),
    }


# ── Read side ────────────────────────────────────────────────────────────────

@router.get("/list")
def vfs_list(
    uid: str = Query(...),
    path: str = Query("documents"),
    _=Depends(require_vfs_token),
) -> dict:
    target = _resolve(uid, path)
    if not target.exists():
        # Tolerate a not-yet-created subdir → empty listing (the browser renders
        # an empty folder rather than erroring on a fresh user).
        return {"path": _rel(uid, target), "entries": []}
    if not target.is_dir():
        raise HTTPException(status_code=400, detail="not a directory")
    entries = []
    for child in sorted(target.iterdir(), key=lambda c: (c.is_file(), c.name.lower())):
        try:
            entries.append(_entry(uid, child))
        except OSError:
            continue
        if len(entries) >= _MAX_LIST_ENTRIES:
            break
    return {"path": _rel(uid, target), "entries": entries}


@router.get("/stat")
def vfs_stat(uid: str = Query(...), path: str = Query(...), _=Depends(require_vfs_token)) -> dict:
    target = _resolve(uid, path, must_exist=True)
    return _entry(uid, target)


@router.get("/read")
def vfs_read(uid: str = Query(...), path: str = Query(...), _=Depends(require_vfs_token)) -> dict:
    target = _resolve(uid, path, must_exist=True)
    if not target.is_file():
        raise HTTPException(status_code=400, detail="not a file")
    size = target.stat().st_size
    if size > _MAX_READ_BYTES:
        raise HTTPException(status_code=413, detail=f"file too large for inline read ({size} B)")
    data = target.read_bytes()
    try:
        return {"path": _rel(uid, target), "size": size, "encoding": "utf-8", "content": data.decode("utf-8")}
    except UnicodeDecodeError:
        raise HTTPException(status_code=415, detail="binary file — use /download")


@router.get("/download")
def vfs_download(uid: str = Query(...), path: str = Query(...), _=Depends(require_vfs_token)):
    target = _resolve(uid, path, must_exist=True)
    if not target.is_file():
        raise HTTPException(status_code=400, detail="not a file")
    return FileResponse(str(target), filename=target.name)


# ── Write side (JSON bodies, matching Bone's other POSTs — no multipart dep) ──

@router.post("/write")
def vfs_write(body: dict = Body(...), _=Depends(require_vfs_token)) -> dict:
    uid, path = body.get("uid", ""), body.get("path", "")
    if not path:
        raise HTTPException(status_code=400, detail="path is required")
    target = _resolve(uid, path)
    if target.is_dir():
        raise HTTPException(status_code=400, detail="path is a directory")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body.get("content", ""), encoding="utf-8")
    return {"ok": True, **_entry(uid, target)}


@router.post("/mkdir")
def vfs_mkdir(body: dict = Body(...), _=Depends(require_vfs_token)) -> dict:
    uid, path = body.get("uid", ""), body.get("path", "")
    if not path:
        raise HTTPException(status_code=400, detail="path is required")
    target = _resolve(uid, path)
    target.mkdir(parents=True, exist_ok=True)
    return {"ok": True, **_entry(uid, target)}


@router.post("/move")
def vfs_move(body: dict = Body(...), _=Depends(require_vfs_token)) -> dict:
    uid = body.get("uid", "")
    src, dst = body.get("src", ""), body.get("dst", "")
    if not src or not dst:
        raise HTTPException(status_code=400, detail="src and dst are required")
    source = _resolve(uid, src, must_exist=True)
    dest = _resolve(uid, dst)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(dest))
    return {"ok": True, **_entry(uid, dest)}


@router.post("/upload")
async def vfs_upload(
    request: Request,
    uid: str = Query(...),
    path: str = Query("documents"),
    filename: str = Query(...),
    _=Depends(require_vfs_token),
) -> dict:
    # Raw-body upload (streamed, capped) → <path>/<filename>. Streaming avoids
    # buffering the whole file and the python-multipart dependency.
    fname = os.path.basename(filename or "upload.bin")
    target = _resolve(uid, f"{path.rstrip('/')}/{fname}" if path else fname)
    if target.is_dir():
        raise HTTPException(status_code=400, detail="path is a directory")
    target.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with target.open("wb") as fh:
        async for chunk in request.stream():
            if not chunk:
                continue
            written += len(chunk)
            if written > _MAX_UPLOAD_BYTES:
                fh.close()
                target.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="upload too large")
            fh.write(chunk)
    return {"ok": True, **_entry(uid, target)}
