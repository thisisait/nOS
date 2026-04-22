"""Docker / Compose action handlers.

Spec: docs/framework-plan.md section 4.2 — ``docker.compose_override_rename``
and ``docker.volume_clone``.

``docker.compose_override_rename`` renames an override yml file in
``~/stacks/<stack>/overrides/`` — pure filesystem move, but kept separate
from ``fs.mv`` because migrations benefit from a dedicated action type
(discoverable, and makes the downstream compose reconciler more explicit).

``docker.volume_clone`` clones volume data.  Two strategies:

1. Bind mount (``src_path`` / ``dst_path`` given) — ``shutil.copytree`` with
   permission preservation.  Preferred path, used by nOS's external-storage
   convention.
2. Named Docker volume (``src_volume`` / ``dst_volume``) — shells out to
   ``docker volume create`` + ``docker run --rm`` with alpine to copy data.

Idempotence: if the destination already holds data and ``overwrite`` is
false, the handler returns ``changed=False``.
"""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import os
import os.path
import shutil
import subprocess


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


def _run(cmd, ctx):
    injected = ctx.get("run_cmd") if ctx else None
    if injected is not None:
        return injected(cmd)
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


# ---------------------------------------------------------------------------
# docker.compose_override_rename

def handle_compose_override_rename(action, ctx):
    """Rename ``~/stacks/<stack>/overrides/<old>.yml`` → ``<new>.yml``.

    action keys:
      - stacks_dir: "~/stacks" by default
      - stack: required, e.g. "infra"
      - from_name: required, old basename (with or without .yml)
      - to_name:   required, new basename (with or without .yml)
      - overwrite: default False
    """
    stack = action.get("stack")
    from_name = action.get("from_name")
    to_name = action.get("to_name")
    if not stack or not from_name or not to_name:
        return _fail("docker.compose_override_rename requires 'stack', 'from_name', 'to_name'")
    stacks_dir = _expand(ctx, action.get("stacks_dir") or "~/stacks")
    overwrite = bool(action.get("overwrite", False))

    def _norm(n):
        return n if n.endswith(".yml") else "%s.yml" % n

    src = os.path.join(stacks_dir, stack, "overrides", _norm(from_name))
    dst = os.path.join(stacks_dir, stack, "overrides", _norm(to_name))

    src_exists = os.path.isfile(src)
    dst_exists = os.path.isfile(dst)
    if not src_exists and dst_exists:
        return _ok(False, reason="already_renamed", src=src, dst=dst)
    if not src_exists and not dst_exists:
        return _fail("compose_override_rename: neither %r nor %r exists" % (src, dst),
                     src=src, dst=dst)
    if dst_exists and not overwrite:
        return _fail("compose_override_rename: dst %r exists and overwrite=false" % dst,
                     src=src, dst=dst)

    if ctx.get("dry_run"):
        return _ok(True, would_rename=True, src=src, dst=dst)

    try:
        if dst_exists and overwrite:
            os.remove(dst)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(src, dst)
    except OSError as exc:
        return _fail("compose_override_rename failed: %s" % exc, src=src, dst=dst)
    return _ok(True, src=src, dst=dst)


# ---------------------------------------------------------------------------
# docker.volume_clone

def handle_volume_clone(action, ctx):
    """Clone volume data from src → dst.

    Modes (mutually exclusive, exactly one required):
      - bind:   ``src_path`` + ``dst_path``  — filesystem copy
      - volume: ``src_volume`` + ``dst_volume`` — docker volume clone

    action keys:
      - src_path / dst_path  (bind mode)
      - src_volume / dst_volume (named-volume mode)
      - overwrite: default False
      - image: default "alpine:3" (named-volume mode only)
    """
    src_path = _expand(ctx, action.get("src_path"))
    dst_path = _expand(ctx, action.get("dst_path"))
    src_volume = action.get("src_volume")
    dst_volume = action.get("dst_volume")
    overwrite = bool(action.get("overwrite", False))
    image = action.get("image") or "alpine:3"

    bind_mode = bool(src_path and dst_path)
    vol_mode = bool(src_volume and dst_volume)
    if bind_mode == vol_mode:
        return _fail(
            "docker.volume_clone requires exactly one of (src_path+dst_path) "
            "or (src_volume+dst_volume)")

    if bind_mode:
        return _clone_bind(src_path, dst_path, overwrite, ctx)
    return _clone_named_volume(src_volume, dst_volume, overwrite, image, ctx)


def _clone_bind(src, dst, overwrite, ctx):
    if not os.path.isdir(src):
        return _fail("volume_clone: src_path %r is not a directory" % src,
                     src=src, dst=dst)
    if os.path.isdir(dst) and os.listdir(dst):
        if not overwrite:
            return _ok(False, reason="dst_non_empty", src=src, dst=dst)
    if ctx.get("dry_run"):
        return _ok(True, would_clone=True, mode="bind", src=src, dst=dst)
    try:
        if os.path.isdir(dst) and overwrite:
            shutil.rmtree(dst)
        os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
        shutil.copytree(src, dst, symlinks=True)
    except OSError as exc:
        return _fail("volume_clone (bind) failed: %s" % exc, src=src, dst=dst)
    return _ok(True, mode="bind", src=src, dst=dst)


def _clone_named_volume(src_vol, dst_vol, overwrite, image, ctx):
    # Check existence.
    inspect = _run(["docker", "volume", "inspect", src_vol], ctx)
    if getattr(inspect, "returncode", 1) != 0:
        return _fail("volume_clone: src volume %r does not exist" % src_vol,
                     src=src_vol, dst=dst_vol)
    dst_inspect = _run(["docker", "volume", "inspect", dst_vol], ctx)
    dst_exists = (getattr(dst_inspect, "returncode", 1) == 0)
    if dst_exists and not overwrite:
        return _ok(False, reason="dst_volume_exists", src=src_vol, dst=dst_vol)

    if ctx.get("dry_run"):
        return _ok(True, would_clone=True, mode="volume", src=src_vol, dst=dst_vol)

    if not dst_exists:
        rc = _run(["docker", "volume", "create", dst_vol], ctx)
        if getattr(rc, "returncode", 1) != 0:
            return _fail("volume_clone: docker volume create failed: %s" %
                         (getattr(rc, "stderr", "") or "").strip(),
                         src=src_vol, dst=dst_vol)

    copy_cmd = [
        "docker", "run", "--rm",
        "-v", "%s:/src:ro" % src_vol,
        "-v", "%s:/dst" % dst_vol,
        image,
        "sh", "-c", "cp -a /src/. /dst/",
    ]
    rc = _run(copy_cmd, ctx)
    if getattr(rc, "returncode", 1) != 0:
        return _fail("volume_clone: docker copy run failed: %s" %
                     (getattr(rc, "stderr", "") or "").strip(),
                     src=src_vol, dst=dst_vol)
    return _ok(True, mode="volume", src=src_vol, dst=dst_vol)
