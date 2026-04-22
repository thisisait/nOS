"""Action handler dispatch for nos_migrate.

Each submodule exports handler callables with the signature:

    handler(action: dict, context: dict) -> dict

where the returned dict must contain at minimum::

    {
        "success": bool,
        "changed": bool,
        # optional
        "error":  "<message>" if not success else None,
        "result": {...}  # free-form, persisted in state event,
    }

``context`` gives handlers access to shared services (logger callback,
AnsibleModule for subprocess helpers, path expansion, dry-run flag, and the
Authentik client factory).  Handlers must be **idempotent** — re-applying an
action whose desired state already holds must return ``changed=False`` with
no side effects.

Spec reference: docs/framework-plan.md section 4.2.
"""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

from . import fs as _fs
from . import launchd as _launchd
from . import docker_compose as _docker_compose
from . import state_ops as _state_ops
from . import exec_shell as _exec_shell
from . import noop as _noop
from . import authentik_proxy as _authentik_proxy


# Canonical dispatch table.  The ``step.action.type`` field (or ``step.rollback.type``)
# resolves via this map.  Keys mirror the spec exactly — do not alias.
ACTION_HANDLERS = {
    # filesystem
    "fs.mv":          _fs.handle_mv,
    "fs.cp":          _fs.handle_cp,
    "fs.rm":          _fs.handle_rm,
    "fs.ensure_dir":  _fs.handle_ensure_dir,
    # launchd
    "launchd.bootout_and_delete": _launchd.handle_bootout_and_delete,
    "launchd.kickstart":          _launchd.handle_kickstart,
    # docker / compose
    "docker.compose_override_rename": _docker_compose.handle_compose_override_rename,
    "docker.volume_clone":            _docker_compose.handle_volume_clone,
    # state ops
    "state.set":                  _state_ops.handle_state_set,
    "state.bump_schema_version":  _state_ops.handle_bump_schema_version,
    # exec
    "exec.shell": _exec_shell.handle_exec_shell,
    # no-op
    "noop": _noop.handle_noop,
    # authentik (delegates to Agent 4's nos_authentik module)
    "authentik.rename_group_prefix":       _authentik_proxy.handle_rename_group_prefix,
    "authentik.rename_oidc_client_prefix": _authentik_proxy.handle_rename_oidc_client_prefix,
    "authentik.migrate_members":           _authentik_proxy.handle_migrate_members,
}


def get_handler(action_type):
    """Return the handler callable for ``action_type`` or raise KeyError."""
    if action_type not in ACTION_HANDLERS:
        raise KeyError("Unknown migration action type: %r" % (action_type,))
    return ACTION_HANDLERS[action_type]


def list_action_types():
    return sorted(ACTION_HANDLERS.keys())
