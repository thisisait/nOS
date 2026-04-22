#!/usr/bin/python3
# -*- coding: utf-8 -*-
# Copyright: (c) 2026, This is AIT — Agentic IT
# GNU General Public License v3.0 or later (see LICENSE at project root)

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
---
module: nos_state
short_description: Read, write, query and introspect the nOS runtime state file.
description:
  - Reads and writes the single-file state document kept at C(~/.nos/state.yml).
  - Supports dotted-path get/set for ad-hoc updates from orchestrator tasks.
  - Supports introspection — given the public C(state/manifest.yml), reports
    the currently installed version + healthy flag of every service by
    querying Docker, Homebrew, launchd, or git.
  - Never fails when the state file is missing; C(read) returns an empty
    skeleton so callers can bootstrap.
  - Honors C(check_mode): dry runs never touch disk.
version_added: "1.0.0"
author: "nOS maintainers"
options:
  action:
    description: What to do.
    type: str
    required: true
    choices: [read, write, get, set, unset, introspect]
  state_path:
    description: Path to the state file. C(~) is expanded against the
      invoking user's home.
    type: str
    default: "~/.nos/state.yml"
  state:
    description: Dict to write. Required for action=write.
    type: dict
  merge:
    description: For action=write, deep-merge into existing state instead of
      replacing wholesale. Default true.
    type: bool
    default: true
  path:
    description: Dotted path (e.g. C(services.grafana.installed)). Required
      for action=get / set / unset.
    type: str
  value:
    description: Value to set. Required for action=set.
    type: raw
  default:
    description: Fallback for action=get when the path is absent.
    type: raw
  manifest_path:
    description: Path to C(state/manifest.yml). Required for action=introspect.
    type: str
  role_vars:
    description: Optional dict of role/default variables used to resolve
      C(version_var), C(data_path_var) and the C(install_<svc>) flag during
      introspection. Pass C(vars) from the Ansible context.
    type: dict
    default: {}
"""

EXAMPLES = r"""
- name: Read current state
  nos_state:
    action: read
  register: nos

- name: Set a nested value
  nos_state:
    action: set
    path: services.grafana.installed
    value: "11.5.0"

- name: Introspect services against the manifest
  nos_state:
    action: introspect
    manifest_path: "{{ playbook_dir }}/state/manifest.yml"
    role_vars: "{{ vars }}"
  register: observed
"""

RETURN = r"""
state:
  description: Full state dict (action=read / write / introspect).
  type: dict
  returned: when action in [read, write, introspect]
value:
  description: Value at dotted path (action=get).
  returned: when action == 'get'
services:
  description: Map of service id -> introspected state (action=introspect).
  type: dict
  returned: when action == 'introspect'
prior_state:
  description: State dict prior to the write.
  type: dict
  returned: when action == 'write'
"""

import os
import sys
import traceback

from ansible.module_utils.basic import AnsibleModule

# The module_utils package is shipped at repo root. When Ansible picks this
# module up via `library = ./library` in ansible.cfg it discovers module_utils
# via `module_utils = ./module_utils` (already declared). During standalone
# pytest runs we also add the repo root to sys.path so the import works.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

try:
    from ansible.module_utils.nos_state_lib import (  # type: ignore[import-not-found]
        DEFAULT_STATE_PATH,
        GENERATOR_ID,
        deep_merge,
        dotted_get,
        dotted_set,
        dotted_unset,
        dump_state,
        empty_state,
        expand_path,
        introspect_all,
        load_manifest,
        load_state,
        to_json_safe,
        utcnow_iso,
    )
except ImportError:
    # Ansible couldn't rewrite the import (e.g. running under pytest).
    from module_utils.nos_state_lib import (  # type: ignore[no-redef]
        DEFAULT_STATE_PATH,
        GENERATOR_ID,
        deep_merge,
        dotted_get,
        dotted_set,
        dotted_unset,
        dump_state,
        empty_state,
        expand_path,
        introspect_all,
        load_manifest,
        load_state,
        to_json_safe,
        utcnow_iso,
    )


def _action_read(module, params):
    state = load_state(params["state_path"])
    module.exit_json(changed=False, state=to_json_safe(state))


def _action_write(module, params):
    if params.get("state") is None:
        module.fail_json(msg="action=write requires 'state' parameter")
    prior = load_state(params["state_path"])
    if params.get("merge", True):
        new_state = deep_merge(prior, params["state"])
    else:
        new_state = dict(params["state"])

    # Bump meta every write.
    new_state["generated_at"] = utcnow_iso()
    new_state.setdefault("generator", GENERATOR_ID)
    new_state.setdefault("schema_version", 1)

    changed = new_state != prior

    if changed and not module.check_mode:
        dump_state(new_state, params["state_path"])

    module.exit_json(
        changed=changed,
        state=to_json_safe(new_state),
        prior_state=to_json_safe(prior),
        path=expand_path(params["state_path"]),
    )


def _action_get(module, params):
    if not params.get("path"):
        module.fail_json(msg="action=get requires 'path' parameter")
    state = load_state(params["state_path"])
    value = dotted_get(state, params["path"], params.get("default"))
    module.exit_json(changed=False, value=to_json_safe(value))


def _action_set(module, params):
    if not params.get("path"):
        module.fail_json(msg="action=set requires 'path' parameter")
    if "value" not in params:
        module.fail_json(msg="action=set requires 'value' parameter")
    state = load_state(params["state_path"])
    changed = dotted_set(state, params["path"], params["value"])
    if changed:
        state["generated_at"] = utcnow_iso()
        if not module.check_mode:
            dump_state(state, params["state_path"])
    module.exit_json(
        changed=changed,
        state=to_json_safe(state),
        path=expand_path(params["state_path"]),
    )


def _action_unset(module, params):
    if not params.get("path"):
        module.fail_json(msg="action=unset requires 'path' parameter")
    state = load_state(params["state_path"])
    changed = dotted_unset(state, params["path"])
    if changed:
        state["generated_at"] = utcnow_iso()
        if not module.check_mode:
            dump_state(state, params["state_path"])
    module.exit_json(changed=changed, state=to_json_safe(state))


def _action_introspect(module, params):
    manifest_path = params.get("manifest_path")
    if not manifest_path:
        module.fail_json(msg="action=introspect requires 'manifest_path'")
    try:
        manifest = load_manifest(manifest_path)
    except Exception as exc:
        module.fail_json(
            msg="Failed to load manifest {!r}: {}".format(manifest_path, exc),
            exception=traceback.format_exc(),
        )
    services = introspect_all(manifest, role_vars=params.get("role_vars") or {})

    # Merge into existing state — introspection is additive.
    state = load_state(params["state_path"])
    state.setdefault("services", {})
    for sid, obs in services.items():
        existing = state["services"].get(sid, {})
        if not isinstance(existing, dict):
            existing = {}
        existing.update({k: v for k, v in obs.items() if v is not None or k in existing})
        state["services"][sid] = existing
    state["generated_at"] = utcnow_iso()

    changed = True  # Introspection records 'generated_at' every run.

    if not module.check_mode:
        try:
            dump_state(state, params["state_path"])
        except Exception as exc:
            module.fail_json(
                msg="Failed to persist state after introspect: {}".format(exc),
                exception=traceback.format_exc(),
            )

    module.exit_json(
        changed=changed,
        services=to_json_safe(services),
        state=to_json_safe(state),
    )


def main():
    module = AnsibleModule(
        argument_spec=dict(
            action=dict(
                type="str",
                required=True,
                choices=["read", "write", "get", "set", "unset", "introspect"],
            ),
            state_path=dict(type="str", default=DEFAULT_STATE_PATH),
            state=dict(type="dict", default=None),
            merge=dict(type="bool", default=True),
            path=dict(type="str", default=None),
            value=dict(type="raw", default=None),
            default=dict(type="raw", default=None),
            manifest_path=dict(type="str", default=None),
            role_vars=dict(type="dict", default={}),
        ),
        supports_check_mode=True,
    )

    params = module.params
    action = params["action"]

    try:
        if action == "read":
            _action_read(module, params)
        elif action == "write":
            _action_write(module, params)
        elif action == "get":
            _action_get(module, params)
        elif action == "set":
            _action_set(module, params)
        elif action == "unset":
            _action_unset(module, params)
        elif action == "introspect":
            _action_introspect(module, params)
        else:  # pragma: no cover — argument_spec guards
            module.fail_json(msg="unknown action: {!r}".format(action))
    except Exception as exc:
        module.fail_json(msg=str(exc), exception=traceback.format_exc())


if __name__ == "__main__":
    main()
