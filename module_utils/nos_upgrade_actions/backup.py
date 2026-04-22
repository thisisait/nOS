"""backup.volume / backup.restore — upgrade-time data snapshots.

Backups are tarballs under ``~/.nos/backups/<label>.tar.gz`` plus a sibling
``<label>.meta.json`` metadata file.  The label is supplied by the recipe
and is required to be unique — the engine enforces this by appending a
run timestamp (``pre-{{ upgrade_id }}-{{ ts }}``).

Rationale: a tarball is portable, inspectable, and round-trips through
``shutil.unpack_archive``.  We deliberately avoid docker volume cp / rsync
here — the data dirs are bind mounts.

Idempotence:

* ``backup.volume`` — if a tarball with the same label already exists,
  returns ``changed=False``.  Writing a fresh backup requires a different
  label (the engine guarantees this via the timestamp suffix).
* ``backup.restore`` — always changed if it runs; the caller is responsible
  for gating with ``when:``.
"""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import errno
import json
import os
import os.path
import shutil
import tarfile
import time


BACKUP_ROOT_DEFAULT = "~/.nos/backups"


def _expand(ctx, path):
    if not path:
        return path
    expander = ctx.get("expand_path") if ctx else None
    if expander is not None:
        return expander(path)
    return os.path.expandvars(os.path.expanduser(path))


def _ok(changed, **extra):
    out = {"success": True, "changed": bool(changed)}
    if extra:
        out["result"] = extra
    return out


def _fail(error, **extra):
    out = {"success": False, "changed": False, "error": str(error)}
    if extra:
        out["result"] = extra
    return out


def _backup_root(ctx):
    root = ctx.get("backup_root") if ctx else None
    return _expand(ctx, root or BACKUP_ROOT_DEFAULT)


def _paths_for(ctx, label):
    root = _backup_root(ctx)
    tgz = os.path.join(root, "%s.tar.gz" % label)
    meta = os.path.join(root, "%s.meta.json" % label)
    return root, tgz, meta


# ---------------------------------------------------------------------------
# backup.volume

def handle_backup_volume(action, ctx):
    """Snapshot a directory to ``<backup_root>/<label>.tar.gz``.

    action keys:
      src   (required) — directory to snapshot
      label (required) — unique label; if missing the engine aborts upstream
    """
    src = _expand(ctx, action.get("src"))
    label = action.get("label")
    if not src or not label:
        return _fail("backup.volume requires 'src' and 'label'")
    if not os.path.isdir(src):
        return _fail("backup.volume: src %r is not a directory" % src, src=src)

    root, tgz, meta = _paths_for(ctx, label)

    if os.path.lexists(tgz):
        return _ok(False, reason="backup_exists", path=tgz, label=label)

    if ctx.get("dry_run"):
        return _ok(True, would_archive=True, src=src, dst=tgz)

    try:
        os.makedirs(root, exist_ok=True)
        # Use a tmp file + rename so a crash mid-write cannot leave a
        # truncated tarball behind with the canonical name.
        tmp = tgz + ".partial"
        if os.path.lexists(tmp):
            os.remove(tmp)
        with tarfile.open(tmp, "w:gz") as tf:
            tf.add(src, arcname=os.path.basename(src.rstrip(os.sep)) or "data")
        os.replace(tmp, tgz)
        meta_blob = {
            "label":       label,
            "src":         src,
            "created_at":  time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "size_bytes":  os.path.getsize(tgz),
            "upgrade_id":  ctx.get("upgrade_id") if ctx else None,
        }
        with open(meta, "w") as fh:
            json.dump(meta_blob, fh, indent=2, sort_keys=True)
    except (OSError, tarfile.TarError) as exc:
        return _fail("backup.volume failed: %s" % exc, src=src, dst=tgz)

    return _ok(True, src=src, dst=tgz, size_bytes=meta_blob["size_bytes"])


# ---------------------------------------------------------------------------
# backup.restore

def handle_backup_restore(action, ctx):
    """Restore a prior tarball back over a directory.

    action keys:
      dst   (required) — directory to restore INTO (will be wiped first)
      label (required) — same label used by backup.volume
      strict (bool, default true) — if true, fail when the tarball is missing
    """
    dst = _expand(ctx, action.get("dst"))
    label = action.get("label")
    strict = bool(action.get("strict", True))
    if not dst or not label:
        return _fail("backup.restore requires 'dst' and 'label'")

    _root, tgz, _meta = _paths_for(ctx, label)
    if not os.path.lexists(tgz):
        if strict:
            return _fail("backup.restore: archive %r not found" % tgz,
                         dst=dst, label=label)
        return _ok(False, reason="archive_missing", label=label)

    if ctx.get("dry_run"):
        return _ok(True, would_restore=True, src=tgz, dst=dst)

    try:
        # Wipe dst contents (preserve the dir itself so bind mounts stay
        # valid inside the container).
        if os.path.isdir(dst):
            for name in os.listdir(dst):
                p = os.path.join(dst, name)
                if os.path.islink(p) or not os.path.isdir(p):
                    os.remove(p)
                else:
                    shutil.rmtree(p)
        else:
            os.makedirs(dst, exist_ok=True)
        with tarfile.open(tgz, "r:gz") as tf:
            # The archive stores everything under a single top-level dir
            # (basename of src at backup time).  Extract into a temp parent,
            # then move children up.
            tmp_parent = dst + ".restore-tmp"
            if os.path.lexists(tmp_parent):
                shutil.rmtree(tmp_parent)
            os.makedirs(tmp_parent)
            _safe_extract(tf, tmp_parent)
            children = os.listdir(tmp_parent)
            if len(children) == 1 and os.path.isdir(os.path.join(tmp_parent, children[0])):
                inner = os.path.join(tmp_parent, children[0])
                for name in os.listdir(inner):
                    shutil.move(os.path.join(inner, name), os.path.join(dst, name))
            else:
                for name in children:
                    shutil.move(os.path.join(tmp_parent, name), os.path.join(dst, name))
            shutil.rmtree(tmp_parent, ignore_errors=True)
    except (OSError, tarfile.TarError) as exc:
        return _fail("backup.restore failed: %s" % exc, dst=dst, label=label)
    except ValueError as exc:
        return _fail("backup.restore refused: %s" % exc, dst=dst, label=label)

    return _ok(True, src=tgz, dst=dst, label=label)


# ---------------------------------------------------------------------------
# internal

def _safe_extract(tf, dest):
    """Refuse tar entries that escape the destination (path traversal)."""
    dest = os.path.abspath(dest)
    for member in tf.getmembers():
        target = os.path.abspath(os.path.join(dest, member.name))
        if not target.startswith(dest + os.sep) and target != dest:
            raise ValueError("unsafe tar entry: %r" % member.name)
    # Python 3.12+ added a filter kwarg; pass the safe "data" filter when
    # available to silence the deprecation warning and future-proof for 3.14.
    try:
        tf.extractall(dest, filter="data")
    except TypeError:
        tf.extractall(dest)
