"""launchd action handlers.

Spec: docs/framework-plan.md section 4.2 — ``launchd.bootout_and_delete`` and
``launchd.kickstart``.

Both handlers shell out to the ``launchctl`` binary via ``subprocess.run``
(no ``shell=True``).  Idempotence: if no matching plist exists, bootout is a
no-op (changed=False); if the target agent is not currently loaded, kickstart
is a no-op (changed=False).
"""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import glob
import os
import os.path
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
    """Run subprocess without shell; tests can inject ``ctx['run_cmd']``."""
    injected = ctx.get("run_cmd") if ctx else None
    if injected is not None:
        return injected(cmd)
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def _user_domain(ctx):
    """Compute the launchctl user domain (gui/<uid>)."""
    uid = ctx.get("uid") if ctx else None
    if uid is None:
        uid = os.getuid()
    return "gui/%d" % int(uid)


# ---------------------------------------------------------------------------
# launchd.bootout_and_delete

def handle_bootout_and_delete(action, ctx):
    """Stop + unload + delete launchagent plists matching a glob.

    action keys:
      - pattern: filename glob, e.g. "com.devboxnos.*.plist"  (REQUIRED)
      - directory: "~/Library/LaunchAgents" by default
    """
    pattern = action.get("pattern")
    if not pattern:
        return _fail("launchd.bootout_and_delete requires 'pattern'")
    directory = _expand(ctx, action.get("directory") or "~/Library/LaunchAgents")
    if not os.path.isdir(directory):
        return _ok(False, reason="directory_missing", directory=directory,
                   pattern=pattern, matched=[])

    full_glob = os.path.join(directory, pattern)
    matches = sorted(glob.glob(full_glob))
    if not matches:
        return _ok(False, reason="no_match", directory=directory,
                   pattern=pattern, matched=[])

    domain = _user_domain(ctx)
    removed = []
    errors = []

    if ctx.get("dry_run"):
        return _ok(True, would_remove=matches, directory=directory, pattern=pattern)

    for plist_path in matches:
        label = _derive_label(plist_path)
        # bootout may fail harmlessly if not loaded; treat nonzero as soft error.
        rc = _run(["launchctl", "bootout", "%s/%s" % (domain, label)], ctx)
        # We deliberately ignore rc — many agents aren't bootstrapped at migration time.
        try:
            os.remove(plist_path)
            removed.append(plist_path)
        except OSError as exc:
            errors.append({"plist": plist_path, "error": str(exc),
                           "bootout_rc": getattr(rc, "returncode", None)})

    if errors:
        return _fail("launchd.bootout_and_delete: %d error(s)" % len(errors),
                     directory=directory, pattern=pattern,
                     removed=removed, errors=errors)
    return _ok(True, directory=directory, pattern=pattern, removed=removed)


def _derive_label(plist_path):
    """Derive the launchd label from a plist filename.

    Convention: the plist filename (sans .plist) *is* the label in nOS.
    """
    base = os.path.basename(plist_path)
    if base.endswith(".plist"):
        base = base[:-len(".plist")]
    return base


# ---------------------------------------------------------------------------
# launchd.kickstart

def handle_kickstart(action, ctx):
    """Restart a loaded launchagent.  Idempotent-ish: if launchctl reports the
    label is unknown, we return changed=False with a diagnostic; tests treat
    this as acceptable (not a hard failure) because migrations may run prior
    to the new agent being bootstrapped.

    action keys:
      - label: launchd label (REQUIRED), e.g. "eu.thisisait.nos.openclaw"
      - kill: bool, default True (passes -k to kickstart)
    """
    label = action.get("label")
    if not label:
        return _fail("launchd.kickstart requires 'label'")
    kill = bool(action.get("kill", True))
    domain = _user_domain(ctx)
    target = "%s/%s" % (domain, label)

    if ctx.get("dry_run"):
        return _ok(True, would_kickstart=target)

    cmd = ["launchctl", "kickstart"]
    if kill:
        cmd.append("-k")
    cmd.append(target)
    res = _run(cmd, ctx)
    rc = getattr(res, "returncode", 1)
    if rc == 0:
        return _ok(True, target=target)
    stderr = (getattr(res, "stderr", "") or "").strip()
    # Typical "Could not find service" — treat as soft no-op.
    if "could not find" in stderr.lower() or "no such process" in stderr.lower():
        return _ok(False, reason="not_loaded", target=target, stderr=stderr)
    return _fail("launchd.kickstart rc=%s: %s" % (rc, stderr), target=target)
