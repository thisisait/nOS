#!/usr/bin/python3
"""
Ansible module: nos_migrate

Public API for the nOS migration engine.  Actions mirror the spec in
docs/framework-plan.md section 4.2:

  - list:          enumerate migration records in a directory
  - list_pending:  enumerate records not yet applied in state.migrations_applied
  - preview:       dry-run the plan for a given record
  - apply:         execute a single migration record end-to-end
  - rollback:      revert a previously applied migration by id

The heavy lifting lives in ``module_utils/nos_migrate_engine.py`` and
``module_utils/nos_migrate_actions/`` — this file is the thin Ansible
wrapper.  Tests import the engine directly and bypass AnsibleModule.

Author: nOS framework — Agent 2.
"""

from __future__ import absolute_import, division, print_function

__metaclass__ = type


DOCUMENTATION = r"""
---
module: nos_migrate
short_description: Execute nOS migration records.
version_added: "1.0"
description:
  - Apply, preview, list, or roll back migration records defined under
    C(migrations/*.yml).  Records describe ordered steps with detect /
    action / verify / rollback predicates.  See
    C(docs/framework-plan.md) section 3.3 and 4.2 for the full schema.
options:
  action:
    description: Which operation to perform.
    type: str
    required: true
    choices: [list, list_pending, preview, apply, rollback]
  migrations_dir:
    description: Directory containing migration YAML files.
    type: path
    default: "{{ playbook_dir }}/migrations"
  migration:
    description: A migration record dict (preview/apply).  Mutually exclusive with migration_id.
    type: dict
  migration_id:
    description: Id of the migration (rollback, or file lookup in migrations_dir).
    type: str
  state:
    description: Current state dict (from nos_state read).  Used by list_pending and rollback.
    type: dict
  state_path:
    description: Path to state.yml.  Default C(~/.nos/state.yml).
    type: path
  schema_path:
    description: Path to migration.schema.json.  Enables jsonschema validation when present.
    type: path
  dry_run:
    description: If true, evaluate plan without side effects.
    type: bool
    default: false
author:
  - "nOS framework — Agent 2"
"""

EXAMPLES = r"""
- name: List pending migrations
  nos_migrate:
    action: list_pending
    state: "{{ _nos_state.state }}"
    migrations_dir: "{{ playbook_dir }}/migrations"
  register: pending

- name: Apply each pending migration
  nos_migrate:
    action: apply
    migration: "{{ item }}"
  loop: "{{ pending.pending }}"
"""

RETURN = r"""
success:   { type: bool,    description: True on successful apply/rollback. }
migrations:{ type: list,    description: List of records (for action=list). }
pending:   { type: list,    description: List of unapplied records (for action=list_pending). }
plan:      { type: list,    description: Per-step preview entries (action=preview). }
steps_applied: { type: int, description: How many forward steps ran (action=apply). }
failed_step:   { type: str, description: Step id that failed, if any. }
"""


import os
import os.path
import sys

from ansible.module_utils.basic import AnsibleModule


# Allow the module_utils package to be imported whether Ansible ships us as
# a plain file or a collection.  Fall back to ``sys.path`` augmentation.
try:
    from ansible.module_utils.nos_migrate_engine import (  # type: ignore
        apply as engine_apply,
        preview as engine_preview,
        list_migrations,
        list_pending,
        load_record,
        rollback_by_id,
    )
    from ansible.module_utils.nos_migrate_actions import list_action_types  # type: ignore
    from ansible.module_utils.nos_migrate_detect import list_predicate_types  # type: ignore
except ImportError:
    _HERE = os.path.dirname(os.path.abspath(__file__))
    _ROOT = os.path.dirname(_HERE)
    if _ROOT not in sys.path:
        sys.path.insert(0, _ROOT)
    from module_utils.nos_migrate_engine import (  # type: ignore
        apply as engine_apply,
        preview as engine_preview,
        list_migrations,
        list_pending,
        load_record,
        rollback_by_id,
    )
    from module_utils.nos_migrate_actions import list_action_types  # type: ignore
    from module_utils.nos_migrate_detect import list_predicate_types  # type: ignore


def _default_migrations_dir(module):
    v = module.params.get("migrations_dir")
    if v:
        return os.path.expanduser(os.path.expandvars(v))
    return os.path.expanduser("~/nOS/migrations")


def _default_schema_path(module):
    v = module.params.get("schema_path")
    if v:
        return os.path.expanduser(os.path.expandvars(v))
    guess = os.path.join(os.path.dirname(_default_migrations_dir(module)),
                         "state", "schema", "migration.schema.json")
    return guess if os.path.isfile(guess) else None


def _build_ctx(module):
    """Assemble the ctx dict consumed by the engine + handlers."""
    ctx = {
        "dry_run": bool(module.params.get("dry_run")),
        "schema_path": _default_schema_path(module),
    }
    state_path = module.params.get("state_path")
    if state_path:
        ctx["state_path"] = os.path.expanduser(os.path.expandvars(state_path))
    return ctx


def main():
    module = AnsibleModule(
        argument_spec={
            "action": {
                "type": "str", "required": True,
                "choices": ["list", "list_pending", "preview", "apply", "rollback", "apply_upgrade"],
            },
            "migrations_dir": {"type": "path", "required": False},
            "migration":      {"type": "dict", "required": False},
            "migration_id":   {"type": "str", "required": False},
            "upgrade":        {"type": "dict", "required": False},
            "state":          {"type": "dict", "required": False, "default": {}},
            "state_path":     {"type": "path", "required": False},
            "schema_path":    {"type": "path", "required": False},
            "dry_run":        {"type": "bool", "required": False, "default": False},
        },
        supports_check_mode=True,
        mutually_exclusive=[("migration", "migration_id")],
    )

    action = module.params["action"]
    migrations_dir = _default_migrations_dir(module)
    ctx = _build_ctx(module)
    if module.check_mode:
        ctx["dry_run"] = True

    try:
        if action == "list":
            records = [rec for _rec_id, _path, rec in list_migrations(migrations_dir)]
            module.exit_json(changed=False, migrations=records,
                             supported_actions=list_action_types(),
                             supported_predicates=list_predicate_types())

        if action == "list_pending":
            pending = list_pending(migrations_dir, module.params["state"] or {})
            module.exit_json(changed=False, pending=pending)

        if action == "preview":
            rec = _resolve_record(module, migrations_dir)
            plan = engine_preview(rec, ctx=ctx)
            module.exit_json(changed=False, **plan)

        if action == "apply":
            rec = _resolve_record(module, migrations_dir)
            result = engine_apply(rec, ctx=ctx, dry_run=ctx["dry_run"])
            success = bool(result.get("success"))
            changed = bool(result.get("steps_applied", 0) > 0) and not ctx["dry_run"]
            if not success:
                module.fail_json(msg=result.get("error") or "migration failed",
                                 **result)
            module.exit_json(changed=changed, **result)

        if action == "rollback":
            mid = module.params.get("migration_id")
            if not mid:
                module.fail_json(msg="rollback requires 'migration_id'")
            result = rollback_by_id(mid, module.params.get("state") or {},
                                    migrations_dir, ctx=ctx)
            if not result.get("success"):
                module.fail_json(msg="rollback reported errors", **result)
            module.exit_json(changed=True, **result)

        if action == "apply_upgrade":
            upgrade = module.params.get("upgrade")
            if not upgrade:
                module.fail_json(msg="apply_upgrade requires 'upgrade' dict "
                                     "(keys: service, recipe, installed, run_ts)")
            result = _apply_upgrade(upgrade, ctx=ctx, dry_run=ctx["dry_run"])
            if not result.get("success"):
                module.fail_json(msg=result.get("error") or "upgrade failed", **result)
            changed = bool(result.get("steps_applied", 0) > 0) and not ctx["dry_run"]
            module.exit_json(changed=changed, **result)

        module.fail_json(msg="unknown action %r" % action)

    except Exception as exc:
        module.fail_json(msg="nos_migrate: %s" % exc)


def _apply_upgrade(upgrade, ctx, dry_run):
    """
    Apply an upgrade recipe end-to-end with upgrade-specific semantics:
        preconditions -> pre[] -> apply[] -> post[]
                                             |
                                             +-- if post fails: rollback[]

    Apply-phase failures do NOT trigger rollback (per spec §3.4 + Agent 6
    flagged contract). Only post-phase failures do.

    Contract with ``tasks/upgrade-engine.yml``: accepts an ``upgrade`` dict
    with keys { service, recipe, installed, recipe_path, run_ts } and
    returns { success, failed_phase?, failed_step?, error?, rolled_back?,
              upgrade_id, steps_applied, duration_sec }.
    """
    import time as _time

    # Import merged dispatch table (migration + upgrade handlers).
    try:
        from ansible.module_utils.nos_upgrade_actions import merged_handlers  # type: ignore
    except ImportError:
        from module_utils.nos_upgrade_actions import merged_handlers  # type: ignore

    handlers = merged_handlers()
    service = upgrade.get("service", "")
    recipe = upgrade.get("recipe") or {}
    run_ts = upgrade.get("run_ts", "")
    installed = upgrade.get("installed", "")
    recipe_id = recipe.get("id", "unknown")
    upgrade_id = "%s-%s-%s" % (service, recipe_id, run_ts) if run_ts else \
                 "%s-%s" % (service, recipe_id)

    step_ctx = dict(ctx) if ctx else {}
    step_ctx.update({
        "upgrade_id": upgrade_id,
        "service": service,
        "recipe": recipe,
        "installed": installed,
        "run_ts": run_ts,
        "from_version_resolved": installed,
        "dry_run": dry_run,
    })

    # Minimal Jinja-like token substitution on step values. Engine is pure
    # Python — we don't have Ansible's full template engine here. Handlers
    # that need rich templating can read step_ctx directly.
    _tokens = {
        "{{ upgrade_id }}":               upgrade_id,
        "{{ recipe.to }}":                str(recipe.get("to", "")),
        "{{ recipe.from_version_resolved }}": installed,
        "{{ installed }}":                installed,
        "{{ run_ts }}":                   run_ts,
        "{{ service }}":                  service,
    }

    def _resolve(step):
        if not isinstance(step, dict):
            return step
        out = {}
        for k, v in step.items():
            if isinstance(v, str):
                rv = v
                for tok, val in _tokens.items():
                    if tok in rv:
                        rv = rv.replace(tok, val)
                out[k] = rv
            elif isinstance(v, dict):
                out[k] = _resolve(v)
            elif isinstance(v, list):
                out[k] = [_resolve(x) if isinstance(x, dict) else x for x in v]
            else:
                out[k] = v
        return out

    def _run_phase(phase_name, steps):
        applied = []
        for raw_step in steps or []:
            sid = raw_step.get("id", "%s-unknown" % phase_name)
            step = _resolve(raw_step)
            action_type = step.get("type")
            if not action_type:
                return False, sid, "step missing 'type'", applied
            handler = handlers.get(action_type)
            if handler is None:
                return False, sid, "no handler for action type %r" % action_type, applied
            if dry_run:
                applied.append((phase_name, sid, {"success": True, "dry_run": True}))
                continue
            try:
                res = handler(step, step_ctx)
            except Exception as exc:
                return False, sid, "handler %s raised: %s" % (action_type, exc), applied
            if not isinstance(res, dict) or not res.get("success", False):
                err = (res.get("error") if isinstance(res, dict) else None) or \
                      "step %s returned unsuccessful" % sid
                return False, sid, err, applied
            applied.append((phase_name, sid, res))
        return True, None, None, applied

    started = _time.monotonic()
    all_applied = []

    if dry_run:
        return {
            "success": True,
            "dry_run": True,
            "upgrade_id": upgrade_id,
            "service": service,
            "recipe_id": recipe_id,
            "from_version": installed,
            "to_version": recipe.get("to"),
            "phases": {
                "pre":   [s.get("id") for s in recipe.get("pre", [])],
                "apply": [s.get("id") for s in recipe.get("apply", [])],
                "post":  [s.get("id") for s in recipe.get("post", [])],
            },
        }

    # Pre phase
    ok, failed_id, err, pre_applied = _run_phase("pre", recipe.get("pre", []))
    all_applied.extend(pre_applied)
    if not ok:
        return {
            "success": False, "failed_phase": "pre", "failed_step": failed_id,
            "error": err, "upgrade_id": upgrade_id, "service": service,
            "steps_applied": len(all_applied),
            "duration_sec": int(_time.monotonic() - started),
        }

    # Apply phase (no rollback on failure — state may be inconsistent but
    # upgrade spec requires operator intervention, not automatic rollback)
    ok, failed_id, err, apply_applied = _run_phase("apply", recipe.get("apply", []))
    all_applied.extend(apply_applied)
    if not ok:
        return {
            "success": False, "failed_phase": "apply", "failed_step": failed_id,
            "error": err, "upgrade_id": upgrade_id, "service": service,
            "steps_applied": len(all_applied),
            "duration_sec": int(_time.monotonic() - started),
        }

    # Post phase (rollback on failure)
    ok, failed_id, err, post_applied = _run_phase("post", recipe.get("post", []))
    all_applied.extend(post_applied)
    if not ok:
        rb_ok, rb_failed_id, rb_err, _rb_applied = _run_phase(
            "rollback", recipe.get("rollback", []))
        return {
            "success": False, "failed_phase": "post", "failed_step": failed_id,
            "error": err, "rolled_back": rb_ok,
            "rollback_error": rb_err, "upgrade_id": upgrade_id, "service": service,
            "steps_applied": len(all_applied),
            "duration_sec": int(_time.monotonic() - started),
        }

    return {
        "success": True,
        "upgrade_id": upgrade_id,
        "service": service,
        "recipe_id": recipe_id,
        "from_version": installed,
        "to_version": recipe.get("to"),
        "steps_applied": len(all_applied),
        "duration_sec": int(_time.monotonic() - started),
    }


def _resolve_record(module, migrations_dir):
    rec = module.params.get("migration")
    if rec:
        return rec
    mid = module.params.get("migration_id")
    if not mid:
        raise ValueError("action requires either 'migration' or 'migration_id'")
    for rec_id, path, loaded in list_migrations(migrations_dir):
        if rec_id == mid:
            return loaded
    # Fallback: try `<migrations_dir>/<id>.yml` directly.
    direct = os.path.join(migrations_dir, "%s.yml" % mid)
    if os.path.isfile(direct):
        return load_record(direct)
    raise ValueError("migration %r not found in %s" % (mid, migrations_dir))


if __name__ == "__main__":
    main()
