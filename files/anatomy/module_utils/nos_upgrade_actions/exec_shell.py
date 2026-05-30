"""Upgrade-flavoured ``exec.shell`` wrapper.

Upgrade recipes were authored with the ergonomic ``command: <shell string>``
convention — pipes, redirects, ``&&``, env-var prefixes — whereas the strict
migrate handler (``nos_migrate_actions.exec_shell``) demands ``cmd:`` and, for
a string command, an explicit ``shell: true``. This wrapper bridges the two
for the UPGRADE dispatch table only (migrations keep the strict contract), so
every exec.shell step — including the safety-critical rollback steps — runs
uniformly without per-step edits across the recipe corpus.

The default-reject security model is unchanged: the underlying handler still
re-checks both ``ctx['migration_allows_shell']`` (recipe-level) and the
step-level ``allow_shell``. This wrapper only normalises step keys.

Spec reference: docs/framework-plan.md section 4.2 — ``exec.shell``.
"""

from __future__ import absolute_import, division, print_function

__metaclass__ = type


def _strict_handler():
    try:
        from ansible.module_utils.nos_migrate_actions.exec_shell import (
            handle_exec_shell as _h)
    except Exception:  # pragma: no cover — non-Ansible test import path
        from module_utils.nos_migrate_actions.exec_shell import (  # type: ignore
            handle_exec_shell as _h)
    return _h


def handle_exec_shell(action, ctx):
    """Normalise recipe ergonomics, then delegate to the strict handler."""
    a = dict(action)
    # `command:` is the recipe-authoring alias for `cmd:`.
    if not a.get("cmd") and a.get("command"):
        a["cmd"] = a["command"]
    # Recipe commands are shell strings (redirects / pipes / &&); default
    # shell=True when cmd is a string and the author didn't set it explicitly.
    if isinstance(a.get("cmd"), str) and "shell" not in a:
        a["shell"] = True
    return _strict_handler()(a, ctx)
