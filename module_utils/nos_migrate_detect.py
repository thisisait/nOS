"""Predicate evaluator for nos_migrate.

Predicates are used in three places:

  - ``applies_if`` at the migration level (gate)
  - ``detect:`` at the step level (skip-if-done guard)
  - ``verify:`` at the step level (post-apply check)
  - ``post_verify:`` at the migration level

Predicate forms accepted — see docs/framework-plan.md section 3.3 and the
table in section 4.2:

  * ``{fs_path_exists: "/some/path"}``
  * ``{fs_path_exists: {path: ..., negate: true}}``
  * ``{type: fs_path_exists, path: ...}``       # alternate form (used in post_verify)
  * ``{launchagent_matches: "com.devboxnos.*"}``
  * ``{launchagents_matching: "pat", count: 0}``
  * ``{launchagent_count: {pattern: ..., count: N}}``
  * ``{authentik_group_exists: "nos-admins"}``
  * ``{authentik_oidc_client_exists: "nos-grafana"}``
  * ``{state_schema_version_lt: 2}``
  * ``{compose_image_tag_is: {service: grafana, tag: "12.0.0", stack: observability}}``
  * combinators: ``{all_of: [...], any_of: [...], not: {...}}``
  * top-level ``negate: true`` on any predicate inverts its result.

The evaluator returns a plain ``bool``.  Errors in side-effectful predicates
(e.g. Authentik unreachable) are propagated as ``PredicateError`` — the
engine decides whether to treat that as a fail-closed or fail-open gate.
"""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import glob
import os
import os.path


class PredicateError(Exception):
    """Raised when a predicate cannot be evaluated (e.g. API down)."""


# --- helpers ---------------------------------------------------------------

def _expand(ctx, path):
    if not path:
        return path
    expander = ctx.get("expand_path") if ctx else None
    if expander is not None:
        return expander(path)
    return os.path.expandvars(os.path.expanduser(path))


def _user_launchagents_dir(ctx):
    return _expand(ctx, (ctx or {}).get("launchagents_dir", "~/Library/LaunchAgents"))


def _authentik(ctx):
    if ctx is None:
        return None
    client = ctx.get("authentik_client")
    if client is not None:
        return client
    factory = ctx.get("authentik_client_factory")
    if callable(factory):
        return factory()
    return None


def _state_client(ctx):
    if ctx is None:
        return None
    c = ctx.get("state_client")
    if c is not None:
        return c
    from .nos_migrate_actions.state_ops import _FileStateClient  # type: ignore
    return _FileStateClient(ctx.get("state_path") or
                            os.path.expanduser("~/.nos/state.yml"))


# --- individual predicates -------------------------------------------------

def _p_fs_path_exists(arg, ctx):
    if isinstance(arg, dict):
        path = arg.get("path")
    else:
        path = arg
    if not path:
        raise PredicateError("fs_path_exists requires 'path'")
    return os.path.lexists(_expand(ctx, path))


def _p_launchagent_matches(arg, ctx):
    pattern = arg if isinstance(arg, str) else arg.get("pattern")
    if not pattern:
        raise PredicateError("launchagent_matches requires 'pattern'")
    d = _user_launchagents_dir(ctx)
    if not os.path.isdir(d):
        return False
    return bool(glob.glob(os.path.join(d, pattern)))


def _p_launchagent_count(arg, ctx):
    if not isinstance(arg, dict):
        raise PredicateError("launchagent_count requires dict form")
    pattern = arg.get("pattern")
    count = arg.get("count")
    if pattern is None or count is None:
        raise PredicateError("launchagent_count requires 'pattern' and 'count'")
    d = _user_launchagents_dir(ctx)
    if not os.path.isdir(d):
        return int(count) == 0
    matches = glob.glob(os.path.join(d, pattern))
    return len(matches) == int(count)


def _p_launchagents_matching_with_count(arg, ctx):
    """Short-hand form used in the retroactive migration spec:
        { launchagents_matching: "com.devboxnos.*", count: 0 }
    If ``count`` is omitted, fall back to 'at least one matches'."""
    if isinstance(arg, str):
        return _p_launchagent_matches(arg, ctx)
    # accept either {pattern, count} or {launchagents_matching, count}
    pattern = arg.get("pattern") or arg.get("launchagents_matching")
    count = arg.get("count")
    if pattern is None:
        raise PredicateError("launchagents_matching requires a pattern")
    d = _user_launchagents_dir(ctx)
    matches = glob.glob(os.path.join(d, pattern)) if os.path.isdir(d) else []
    if count is None:
        return bool(matches)
    return len(matches) == int(count)


def _p_authentik_group_exists(arg, ctx):
    name = arg if isinstance(arg, str) else arg.get("name")
    if not name:
        raise PredicateError("authentik_group_exists requires 'name'")
    client = _authentik(ctx)
    if client is None:
        # Graceful degradation: if the Authentik client isn't available in ctx
        # (orchestrator did not wire one, or Authentik is down), treat the
        # predicate as False rather than raising. This lets migrations with
        # mixed predicates (any_of over fs + launchd + authentik) proceed
        # correctly during early boot phases. Set ctx['authentik_required']=True
        # to restore strict behavior (raises PredicateError).
        if (ctx or {}).get("authentik_required"):
            raise PredicateError("authentik_group_exists: no Authentik client "
                                 "available (ctx['authentik_required']=True)")
        return False
    return bool(client.get_group(name))


def _p_authentik_oidc_client_exists(arg, ctx):
    name = arg if isinstance(arg, str) else arg.get("name")
    if not name:
        raise PredicateError("authentik_oidc_client_exists requires 'name'")
    client = _authentik(ctx)
    if client is None:
        if (ctx or {}).get("authentik_required"):
            raise PredicateError("authentik_oidc_client_exists: no Authentik client available")
        return False
    # nos_authentik may expose either get_oidc_client(name) or list_oidc_clients().
    if hasattr(client, "get_oidc_client"):
        return bool(client.get_oidc_client(name))
    if hasattr(client, "list_oidc_clients"):
        for c in client.list_oidc_clients() or []:
            if isinstance(c, dict) and c.get("name") == name:
                return True
            if hasattr(c, "name") and getattr(c, "name") == name:
                return True
        return False
    raise PredicateError("authentik client has neither get_oidc_client "
                         "nor list_oidc_clients")


def _p_state_schema_version_lt(arg, ctx):
    if isinstance(arg, dict):
        target = arg.get("version") or arg.get("value")
    else:
        target = arg
    if target is None:
        raise PredicateError("state_schema_version_lt requires a version")
    sc = _state_client(ctx)
    current = sc.get("schema_version", 0) if sc else 0
    try:
        return int(current or 0) < int(target)
    except (TypeError, ValueError) as exc:
        raise PredicateError("state_schema_version_lt: %s" % exc)


def _p_compose_image_tag_is(arg, ctx):
    """Check that a compose override declares the given image tag.

    arg keys: service, tag, [stack], [overrides_dir="~/stacks/<stack>/overrides"]
    """
    if not isinstance(arg, dict):
        raise PredicateError("compose_image_tag_is requires dict form")
    service = arg.get("service")
    tag = arg.get("tag")
    stack = arg.get("stack")
    if not service or tag is None:
        raise PredicateError("compose_image_tag_is requires 'service' and 'tag'")
    overrides_dir = arg.get("overrides_dir")
    if not overrides_dir:
        if not stack:
            raise PredicateError(
                "compose_image_tag_is requires 'stack' or 'overrides_dir'")
        overrides_dir = _expand(ctx, "~/stacks/%s/overrides" % stack)
    else:
        overrides_dir = _expand(ctx, overrides_dir)
    candidate_paths = [
        os.path.join(overrides_dir, "%s.yml" % service),
        os.path.join(overrides_dir, "%s.yaml" % service),
    ]
    try:
        import yaml  # noqa: WPS433
    except ImportError as exc:
        raise PredicateError("PyYAML required for compose_image_tag_is: %s" % exc)
    for path in candidate_paths:
        if not os.path.isfile(path):
            continue
        with open(path, "r") as fh:
            try:
                data = yaml.safe_load(fh) or {}
            except yaml.YAMLError as exc:
                raise PredicateError("invalid YAML at %s: %s" % (path, exc))
        services = (data.get("services") or {}) if isinstance(data, dict) else {}
        svc = services.get(service)
        if not isinstance(svc, dict):
            continue
        image = svc.get("image")
        if not image:
            continue
        want = str(tag)
        if ":" in image:
            _, found = image.rsplit(":", 1)
        else:
            found = "latest"
        if found == want:
            return True
    return False


# dispatch for single-predicate evaluation
_SIMPLE = {
    "fs_path_exists":             _p_fs_path_exists,
    "launchagent_matches":        _p_launchagent_matches,
    "launchagent_count":          _p_launchagent_count,
    "launchagents_matching":      _p_launchagents_matching_with_count,
    "authentik_group_exists":     _p_authentik_group_exists,
    "authentik_oidc_client_exists": _p_authentik_oidc_client_exists,
    "state_schema_version_lt":    _p_state_schema_version_lt,
    "compose_image_tag_is":       _p_compose_image_tag_is,
}


# --- public API ------------------------------------------------------------

def evaluate(predicate, ctx=None):
    """Evaluate a predicate dict (or list-of-predicates interpreted as all_of)
    to bool.  Raises ``PredicateError`` for malformed predicates or when a
    side-effectful check cannot be performed."""
    if predicate is None:
        return True
    if isinstance(predicate, bool):
        return predicate
    if isinstance(predicate, list):
        return all(evaluate(p, ctx) for p in predicate)
    if not isinstance(predicate, dict):
        raise PredicateError("predicate must be dict/list/bool, got %r" % type(predicate))

    # combinators (note: JSON-schema-friendly; we also accept the python-reserved
    # word "not" as a dict key since YAML allows it).
    if "all_of" in predicate:
        return all(evaluate(p, ctx) for p in (predicate.get("all_of") or []))
    if "any_of" in predicate:
        return any(evaluate(p, ctx) for p in (predicate.get("any_of") or []))
    if "not" in predicate:
        return not evaluate(predicate.get("not"), ctx)

    # alternate form used in post_verify:
    #   {type: fs_path_exists, path: "~/.nos/secrets.yml"}
    if "type" in predicate and len(predicate) >= 1 and set(predicate.keys()) != {"type"}:
        ptype = predicate["type"]
        if ptype in _SIMPLE:
            args = {k: v for k, v in predicate.items() if k not in ("type", "negate")}
            # Accept single-arg short form.
            if len(args) == 1 and "path" in args and ptype == "fs_path_exists":
                result = _SIMPLE[ptype](args["path"], ctx)
            else:
                result = _SIMPLE[ptype](args if args else {}, ctx)
            if predicate.get("negate"):
                return not result
            return result

    # shorthand form: exactly one predicate key, value is the argument.
    # Special case: "launchagents_matching: <pattern>" may carry a sibling
    # "count:" key — treat the full dict as the predicate arg.
    keys = [k for k in predicate.keys() if k not in ("negate",)]
    type_keys = [k for k in keys if k in _SIMPLE]
    if len(type_keys) != 1:
        raise PredicateError(
            "predicate must contain exactly one type key (got: %r)" % list(predicate.keys()))
    key = type_keys[0]
    extras = [k for k in keys if k != key]
    if extras:
        # Pass the full dict (minus 'negate') so the handler sees siblings like 'count'.
        arg = {k: v for k, v in predicate.items() if k != "negate"}
    else:
        arg = predicate[key]
    result = _SIMPLE[key](arg, ctx)
    if predicate.get("negate"):
        return not result
    return bool(result)


def list_predicate_types():
    return sorted(list(_SIMPLE.keys()) + ["all_of", "any_of", "not"])
