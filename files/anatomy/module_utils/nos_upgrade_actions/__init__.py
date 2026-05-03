"""Action handler dispatch for the upgrade engine.

Mirrors ``nos_migrate_actions`` but provides the handlers specific to
version transitions (backups, HTTP probes, compose tag manipulation,
arbitrary Ansible module invocation).

Each handler follows the same contract::

    handler(action: dict, context: dict) -> dict

with the same return shape (``success``, ``changed``, optional ``error`` /
``result``).  The engine merges this map with Agent 2's ``ACTION_HANDLERS``
so upgrade recipes can also use ``fs.*`` / ``exec.shell`` / ``noop``.

Spec reference: docs/framework-plan.md section 3.4 and 7.2.
"""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

from . import backup as _backup
from . import http_ops as _http_ops
from . import compose_ops as _compose_ops
from . import custom_module as _custom_module


UPGRADE_ACTION_HANDLERS = {
    "backup.volume":   _backup.handle_backup_volume,
    "backup.restore":  _backup.handle_backup_restore,
    "http.wait":       _http_ops.handle_http_wait,
    "http.get_all":    _http_ops.handle_http_get_all,
    "compose.set_image_tag":    _compose_ops.handle_set_image_tag,
    "compose.restart_service":  _compose_ops.handle_restart_service,
    "custom.module":   _custom_module.handle_custom_module,
}


def get_handler(action_type):
    """Return the handler callable for ``action_type`` or raise KeyError."""
    if action_type not in UPGRADE_ACTION_HANDLERS:
        raise KeyError("Unknown upgrade action type: %r" % (action_type,))
    return UPGRADE_ACTION_HANDLERS[action_type]


def list_action_types():
    return sorted(UPGRADE_ACTION_HANDLERS.keys())


def merged_handlers():
    """Return a single dispatch table combining migration + upgrade handlers.

    Called by the engine on startup.  If a key collides (none should), the
    upgrade handler wins — recipes are the ones invoking these types.
    """
    try:
        from ansible.module_utils.nos_migrate_actions import ACTION_HANDLERS as _MIG
    except Exception:  # pragma: no cover — unit tests may not have Ansible installed
        try:
            from module_utils.nos_migrate_actions import ACTION_HANDLERS as _MIG  # type: ignore
        except Exception:
            _MIG = {}
    combined = dict(_MIG)
    combined.update(UPGRADE_ACTION_HANDLERS)
    return combined
