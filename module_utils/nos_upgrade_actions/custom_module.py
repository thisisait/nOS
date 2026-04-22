"""custom.module — escape hatch to invoke any Ansible module from a recipe.

Recipes occasionally need to call a stock Ansible module (``uri``,
``include_tasks``, ``community.docker.docker_container_info``, etc.) for
verification that the typed upgrade action set doesn't cover.  This
handler records the intent and defers the actual invocation to the engine
(``tasks/upgrade-engine.yml``), which is in the Ansible context and can
use ``ansible.builtin.include_module``-like constructs.

The Python layer here only validates the call shape — it never imports
Ansible at runtime.  The engine side uses this handler's return payload
as a directive: ``{"success": True, "deferred": True, "module": ...,
"args": ...}`` tells the Ansible task list to run the module for real.
"""

from __future__ import absolute_import, division, print_function

__metaclass__ = type


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


def handle_custom_module(action, ctx):
    """Validate a custom-module directive.

    action keys:
      module (required) — Ansible module name (FQCN preferred)
      args   (dict, default {}) — module arguments
      register_as (optional str) — engine will stash the result in this
        key inside ctx['registers'] for later steps to Jinja-reference
      ignore_errors (bool, default false) — forwarded to the engine
    """
    module = action.get("module")
    if not module:
        return _fail("custom.module requires 'module'")
    args = action.get("args") or {}
    if not isinstance(args, dict):
        return _fail("custom.module 'args' must be a mapping")

    injected = ctx.get("invoke_module") if ctx else None
    if injected is not None:
        # Tests / engine can plug in a real dispatcher here.
        try:
            result = injected(module=module, args=args, ctx=ctx)
        except Exception as exc:  # pragma: no cover — injector controls
            return _fail("custom.module invocation failed: %s" % exc,
                         module=module, args=args)
        if not isinstance(result, dict):
            return _fail("custom.module injector returned non-dict: %r" % type(result).__name__)
        # Respect injector's own success flag if present.
        success = bool(result.get("success", True))
        out = {"success": success, "changed": bool(result.get("changed", False))}
        if "error" in result:
            out["error"] = result["error"]
        out["result"] = {k: v for k, v in result.items()
                         if k not in ("success", "changed", "error")}
        return out

    # Pure-Python mode: return a deferred directive.  The Ansible-side
    # upgrade-engine task is responsible for seeing ``deferred=true`` and
    # actually invoking the module.  ``changed=False`` here is accurate —
    # nothing has happened yet.
    if ctx.get("dry_run"):
        return _ok(False, deferred=True, dry_run=True, module=module, args=args)

    return _ok(False, deferred=True, module=module, args=args,
               register_as=action.get("register_as"),
               ignore_errors=bool(action.get("ignore_errors", False)))
