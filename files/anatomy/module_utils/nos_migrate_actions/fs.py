"""Filesystem action handlers (fs.mv / fs.cp / fs.rm / fs.ensure_dir).

All handlers are idempotent: if the desired post-state is already in place,
they return ``changed=False`` without touching the filesystem.

Spec reference: docs/framework-plan.md section 4.2, ``fs.*`` action types.
"""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import os
import os.path
import shutil


# ---------------------------------------------------------------------------
# helpers

def _expand(ctx, path):
    """Expand ``~`` and env vars.  ctx['expand_path'] may override for tests."""
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


# ---------------------------------------------------------------------------
# fs.mv

def handle_mv(action, ctx):
    """Rename / move a path.  Idempotent: if dst already exists and src does
    not, return ``changed=False``.

    action keys: src, dst, [overwrite=False]
    """
    src = _expand(ctx, action.get("src"))
    dst = _expand(ctx, action.get("dst"))
    overwrite = bool(action.get("overwrite", False))
    if not src or not dst:
        return _fail("fs.mv requires 'src' and 'dst'")

    src_exists = os.path.lexists(src)
    dst_exists = os.path.lexists(dst)

    # Already migrated.
    if not src_exists and dst_exists:
        return _ok(False, reason="already_moved", src=src, dst=dst)

    if not src_exists and not dst_exists:
        return _fail("fs.mv: neither src %r nor dst %r exists" % (src, dst),
                     src=src, dst=dst)

    if dst_exists and not overwrite:
        return _fail("fs.mv: dst %r already exists and overwrite=false" % dst,
                     src=src, dst=dst)

    if ctx.get("dry_run"):
        return _ok(True, would_move=True, src=src, dst=dst)

    try:
        if dst_exists and overwrite:
            _remove_path(dst)
        # Ensure parent dir of dst exists.
        parent = os.path.dirname(os.path.abspath(dst))
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)
        shutil.move(src, dst)
    except OSError as exc:
        return _fail("fs.mv failed: %s" % exc, src=src, dst=dst)
    return _ok(True, src=src, dst=dst)


# ---------------------------------------------------------------------------
# fs.cp

def handle_cp(action, ctx):
    """Copy path.  Idempotent: existing dst of same type → changed=False
    without content verification (deep equality is out of scope — migrations
    should use verify: predicates for that).

    action keys: src, dst, [recursive=True], [overwrite=False]
    """
    src = _expand(ctx, action.get("src"))
    dst = _expand(ctx, action.get("dst"))
    recursive = bool(action.get("recursive", True))
    overwrite = bool(action.get("overwrite", False))
    if not src or not dst:
        return _fail("fs.cp requires 'src' and 'dst'")
    if not os.path.lexists(src):
        return _fail("fs.cp: src %r does not exist" % src, src=src, dst=dst)
    if os.path.lexists(dst):
        if not overwrite:
            return _ok(False, reason="dst_exists", src=src, dst=dst)
    if ctx.get("dry_run"):
        return _ok(True, would_copy=True, src=src, dst=dst)
    try:
        if os.path.lexists(dst) and overwrite:
            _remove_path(dst)
        parent = os.path.dirname(os.path.abspath(dst))
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)
        if os.path.isdir(src) and not os.path.islink(src):
            if not recursive:
                return _fail("fs.cp: src is directory but recursive=false",
                             src=src, dst=dst)
            shutil.copytree(src, dst, symlinks=True)
        else:
            shutil.copy2(src, dst, follow_symlinks=False)
    except OSError as exc:
        return _fail("fs.cp failed: %s" % exc, src=src, dst=dst)
    return _ok(True, src=src, dst=dst)


# ---------------------------------------------------------------------------
# fs.rm

def handle_rm(action, ctx):
    """Remove a path.  Idempotent: missing path → changed=False.

    action keys: path, [recursive=True], [missing_ok=True]
    """
    path = _expand(ctx, action.get("path"))
    recursive = bool(action.get("recursive", True))
    missing_ok = bool(action.get("missing_ok", True))
    if not path:
        return _fail("fs.rm requires 'path'")
    if not os.path.lexists(path):
        if missing_ok:
            return _ok(False, reason="missing", path=path)
        return _fail("fs.rm: path %r does not exist" % path, path=path)
    if ctx.get("dry_run"):
        return _ok(True, would_remove=True, path=path)
    try:
        _remove_path(path, recursive=recursive)
    except OSError as exc:
        return _fail("fs.rm failed: %s" % exc, path=path)
    return _ok(True, path=path)


# ---------------------------------------------------------------------------
# fs.ensure_dir

def handle_ensure_dir(action, ctx):
    """Create a directory (``mkdir -p``).  Idempotent.

    action keys: path, [mode] (octal int or str like "0o755"), [owner_check=False]
    """
    path = _expand(ctx, action.get("path"))
    mode = action.get("mode")
    if not path:
        return _fail("fs.ensure_dir requires 'path'")
    if os.path.isdir(path):
        # If a mode is requested and it's already set, no change.
        if mode is not None and not ctx.get("dry_run"):
            want = _parse_mode(mode)
            have = os.stat(path).st_mode & 0o777
            if want is not None and have != want:
                os.chmod(path, want)
                return _ok(True, path=path, mode_fixed=True)
        return _ok(False, reason="exists", path=path)
    if os.path.lexists(path):
        return _fail("fs.ensure_dir: path %r exists and is not a directory" % path,
                     path=path)
    if ctx.get("dry_run"):
        return _ok(True, would_create=True, path=path)
    try:
        os.makedirs(path, exist_ok=True)
        if mode is not None:
            parsed = _parse_mode(mode)
            if parsed is not None:
                os.chmod(path, parsed)
    except OSError as exc:
        return _fail("fs.ensure_dir failed: %s" % exc, path=path)
    return _ok(True, path=path)


# ---------------------------------------------------------------------------
# low-level helpers

def _remove_path(path, recursive=True):
    if os.path.islink(path) or not os.path.isdir(path):
        os.remove(path)
        return
    if recursive:
        shutil.rmtree(path)
    else:
        os.rmdir(path)


def _parse_mode(mode):
    if mode is None:
        return None
    if isinstance(mode, int):
        return mode
    if isinstance(mode, str):
        s = mode.strip()
        try:
            if s.startswith("0o") or s.startswith("0O"):
                return int(s, 8)
            if s.startswith("0") and len(s) > 1:
                return int(s, 8)
            return int(s, 8)
        except ValueError:
            return None
    return None
