"""Explicit no-op action.

Used primarily as the ``rollback.type`` for irreversible forward steps
(e.g. a ``launchd.bootout_and_delete`` whose inverse would require re-
rendering the playbook).  The engine records a structured reason so the
operator can see *why* a step was non-reversible.

Spec reference: docs/framework-plan.md section 4.2 — ``noop``; also the
inline comment in the retroactive migration example.
"""

from __future__ import absolute_import, division, print_function

__metaclass__ = type


def handle_noop(action, ctx):
    reason = action.get("reason") or "no-op"
    return {
        "success": True,
        "changed": False,
        "result": {"noop": True, "reason": reason},
    }
