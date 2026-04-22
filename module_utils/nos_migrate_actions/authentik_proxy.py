"""Authentik action handlers — delegates to Agent 4's ``nos_authentik`` module.

The real implementation lives in ``library/nos_authentik.py``.  This file
adapts the migration-step contract to the nos_authentik public API.  We
resolve the Authentik client in this priority order:

1. ``ctx['authentik_client']`` — explicit injection (tests + the engine use
   this in most cases).
2. ``ctx['authentik_client_factory']()`` — lazy factory for production runs.
3. A conditional import of ``library.nos_authentik`` (Agent 4).

If nos_authentik is not available and no client is injected, we return a
clear error rather than silently proceeding — this is important because
Authentik mutations are NOT reversible by fs-level rollback.

Spec reference: docs/framework-plan.md sections 4.2 and 4.3.
"""

from __future__ import absolute_import, division, print_function

__metaclass__ = type


_MISSING_ERR = (
    "authentik action requires an Authentik client: inject ctx['authentik_client'] "
    "or ensure Agent 4's library/nos_authentik.py is importable."
)


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


def _resolve_client(ctx):
    if ctx is None:
        return None
    client = ctx.get("authentik_client")
    if client is not None:
        return client
    factory = ctx.get("authentik_client_factory")
    if callable(factory):
        return factory()
    # Last-resort lazy import — optional, will succeed only once Agent 4 lands.
    try:
        from ansible_collections.community.general import plugins  # noqa: F401
    except Exception:  # pragma: no cover
        pass
    try:
        # Agent 4 will expose a helper at library.nos_authentik:make_client()
        from library import nos_authentik  # type: ignore
    except Exception:
        return None
    if hasattr(nos_authentik, "make_client"):
        try:
            return nos_authentik.make_client()
        except Exception:  # pragma: no cover - depends on runtime config
            return None
    return None


# ---------------------------------------------------------------------------

def handle_rename_group_prefix(action, ctx):
    """Delegate to ``nos_authentik.rename_group_prefix``.

    action keys: from_prefix, to_prefix, [preserve_members=True],
                 [preserve_policies=True], [dry_run?]
    """
    from_prefix = action.get("from_prefix")
    to_prefix = action.get("to_prefix")
    if not from_prefix or not to_prefix:
        return _fail("authentik.rename_group_prefix requires 'from_prefix' and 'to_prefix'")
    client = _resolve_client(ctx)
    if client is None:
        return _fail(_MISSING_ERR)
    kwargs = {
        "from_prefix": from_prefix,
        "to_prefix": to_prefix,
        "preserve_members": action.get("preserve_members", True),
        "preserve_policies": action.get("preserve_policies", True),
    }
    if ctx.get("dry_run"):
        return _ok(True, would_rename=True, **kwargs)
    try:
        res = client.rename_group_prefix(**kwargs)
    except Exception as exc:
        return _fail("authentik.rename_group_prefix failed: %s" % exc, **kwargs)
    return _build_result(res, **kwargs)


def handle_rename_oidc_client_prefix(action, ctx):
    """Delegate to ``nos_authentik.rename_oidc_client_prefix``.

    action keys: from_prefix, to_prefix
    """
    from_prefix = action.get("from_prefix")
    to_prefix = action.get("to_prefix")
    if not from_prefix or not to_prefix:
        return _fail(
            "authentik.rename_oidc_client_prefix requires 'from_prefix' and 'to_prefix'")
    client = _resolve_client(ctx)
    if client is None:
        return _fail(_MISSING_ERR)
    if ctx.get("dry_run"):
        return _ok(True, would_rename=True, from_prefix=from_prefix, to_prefix=to_prefix)
    try:
        res = client.rename_oidc_client_prefix(
            from_prefix=from_prefix, to_prefix=to_prefix)
    except Exception as exc:
        return _fail("authentik.rename_oidc_client_prefix failed: %s" % exc,
                     from_prefix=from_prefix, to_prefix=to_prefix)
    return _build_result(res, from_prefix=from_prefix, to_prefix=to_prefix)


def handle_migrate_members(action, ctx):
    """Delegate to ``nos_authentik.migrate_members``.

    action keys: from_group, to_group
    """
    from_group = action.get("from_group")
    to_group = action.get("to_group")
    if not from_group or not to_group:
        return _fail("authentik.migrate_members requires 'from_group' and 'to_group'")
    client = _resolve_client(ctx)
    if client is None:
        return _fail(_MISSING_ERR)
    if ctx.get("dry_run"):
        return _ok(True, would_migrate=True, from_group=from_group, to_group=to_group)
    try:
        res = client.migrate_members(from_group=from_group, to_group=to_group)
    except Exception as exc:
        return _fail("authentik.migrate_members failed: %s" % exc,
                     from_group=from_group, to_group=to_group)
    return _build_result(res, from_group=from_group, to_group=to_group)


def _build_result(res, **context_kwargs):
    """Normalise nos_authentik return values into the action contract."""
    if isinstance(res, dict):
        success = bool(res.get("success", True))
        changed = bool(res.get("changed", False))
        out = {"success": success, "changed": changed}
        # merge result data, preserving handler-known context.
        merged = {}
        merged.update(context_kwargs)
        if "result" in res and isinstance(res["result"], dict):
            merged.update(res["result"])
        else:
            extras = {k: v for k, v in res.items()
                      if k not in ("success", "changed", "error")}
            merged.update(extras)
        if merged:
            out["result"] = merged
        if not success and "error" in res:
            out["error"] = res["error"]
        return out
    # Fallback: truthy == changed, falsy == no change.
    return _ok(bool(res), **context_kwargs)
