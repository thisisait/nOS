"""Escape hatch: ``exec.shell``.

Default-reject.  Runs **only** when both:

  - the migration record declares ``allow_shell: true`` at the top level, AND
  - the step's action declares ``allow_shell: true``.

The engine is responsible for threading the migration-level flag into
``ctx['migration_allows_shell']`` before dispatching.  This handler defends
in depth by re-checking both flags.

Spec reference: docs/framework-plan.md section 4.2 — ``exec.shell``.
"""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import subprocess


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


def _run(cmd, shell, ctx):
    injected = ctx.get("run_cmd") if ctx else None
    if injected is not None:
        return injected(cmd)
    return subprocess.run(cmd, shell=bool(shell), capture_output=True, text=True,
                          check=False)


def handle_exec_shell(action, ctx):
    """Run an arbitrary shell command — gated.

    action keys:
      - cmd:          REQUIRED. string (shell=True) or list (shell=False).
      - allow_shell:  MUST be true (step-level).
      - shell:        default False — if True, cmd runs via /bin/sh -c.
      - cwd:          optional working directory.
      - expect_rc:    expected return code, default 0.
      - changed:      bool, default True — what this action reports when rc==expected.
    """
    if not ctx.get("migration_allows_shell"):
        return _fail("exec.shell refused: migration record must declare "
                     "top-level 'allow_shell: true'")
    if not action.get("allow_shell"):
        return _fail("exec.shell refused: step must declare 'allow_shell: true'")

    cmd = action.get("cmd")
    if not cmd:
        return _fail("exec.shell requires 'cmd'")
    shell = bool(action.get("shell", False))
    expect_rc = int(action.get("expect_rc", 0))
    reported_changed = bool(action.get("changed", True))

    # When not using shell, require a list to avoid implicit splitting.
    if not shell and isinstance(cmd, str):
        return _fail("exec.shell: when shell=false, cmd must be a list, got str")
    if shell and not isinstance(cmd, str):
        return _fail("exec.shell: when shell=true, cmd must be a string")

    if ctx.get("dry_run"):
        return _ok(True, would_exec=True, cmd=cmd, shell=shell)

    try:
        res = _run(cmd, shell, ctx)
    except OSError as exc:
        return _fail("exec.shell: spawn failed: %s" % exc, cmd=cmd)
    rc = getattr(res, "returncode", 1)
    stdout = getattr(res, "stdout", "") or ""
    stderr = getattr(res, "stderr", "") or ""
    if rc != expect_rc:
        return _fail("exec.shell: rc=%s (expected %s): %s" %
                     (rc, expect_rc, stderr.strip()),
                     cmd=cmd, rc=rc, stdout=stdout, stderr=stderr)
    return _ok(reported_changed, rc=rc, stdout=stdout, stderr=stderr, cmd=cmd)
