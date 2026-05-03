"""State operations — ``state.set`` and ``state.bump_schema_version``.

These handlers call Agent 1's ``nos_state`` module.  We use two integration
paths, tried in order:

1. ``ctx['state_client']`` — an object providing ``get(path, default)`` and
   ``set(path, value)``.  Tests inject an in-memory fake; the engine injects
   a lightweight wrapper that reads/writes ``~/.nos/state.yml`` directly.
2. A direct import of ``nos_state`` helpers (when Agent 1 ships them).  If
   neither is available, we fall back to a YAML round-trip via PyYAML.

Spec reference: docs/framework-plan.md sections 3.2, 4.1 and 4.2.
"""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import copy
import os
import os.path


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


# ---------------------------------------------------------------------------
# minimal state client used when ctx doesn't provide one

class _FileStateClient(object):
    """Read + patch ``state_path`` YAML.  Load once per call (small file).

    Used as a fallback when the caller didn't inject a state client.  The
    real nos_state module (Agent 1) is a drop-in replacement.
    """

    def __init__(self, state_path):
        self.path = state_path

    def _load(self):
        try:
            import yaml  # noqa: WPS433 - optional dep, always present in Ansible env
        except ImportError as exc:  # pragma: no cover - env always has yaml
            raise RuntimeError("PyYAML not available: %s" % exc)
        if not os.path.isfile(self.path):
            return {}
        with open(self.path, "r") as fh:
            return yaml.safe_load(fh) or {}

    def _dump(self, data):
        import yaml
        parent = os.path.dirname(os.path.abspath(self.path))
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)
        with open(self.path, "w") as fh:
            yaml.safe_dump(data, fh, sort_keys=False, default_flow_style=False)

    def get(self, dotted, default=None):
        data = self._load()
        cur = data
        for part in _split_path(dotted):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    def set(self, dotted, value):
        data = self._load()
        prior = copy.deepcopy(data)
        _set_dotted(data, dotted, value)
        if data == prior:
            return False
        self._dump(data)
        return True


def _split_path(dotted):
    if isinstance(dotted, (list, tuple)):
        return list(dotted)
    if not dotted:
        return []
    return [p for p in str(dotted).split(".") if p]


def _set_dotted(container, dotted, value):
    parts = _split_path(dotted)
    if not parts:
        raise ValueError("empty state path")
    cur = container
    for p in parts[:-1]:
        nxt = cur.get(p)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[p] = nxt
        cur = nxt
    cur[parts[-1]] = value


def _resolve_client(ctx):
    client = ctx.get("state_client") if ctx else None
    if client is not None:
        return client
    state_path = ctx.get("state_path") if ctx else None
    if not state_path:
        state_path = os.path.expanduser("~/.nos/state.yml")
    return _FileStateClient(state_path)


# ---------------------------------------------------------------------------
# state.set

def handle_state_set(action, ctx):
    """Set a dotted-path key in ``~/.nos/state.yml``.

    action keys:
      - path:  dotted key, e.g. "identifiers.launchd_prefix"
      - value: any YAML-serialisable value
    """
    path = action.get("path")
    if not path:
        return _fail("state.set requires 'path'")
    if "value" not in action:
        return _fail("state.set requires 'value'")
    value = action.get("value")
    client = _resolve_client(ctx)
    prior = client.get(path, None)
    if prior == value:
        return _ok(False, reason="unchanged", path=path, value=value)
    if ctx.get("dry_run"):
        return _ok(True, would_set=True, path=path, value=value, prior=prior)
    changed = bool(client.set(path, value))
    return _ok(changed, path=path, value=value, prior=prior)


# ---------------------------------------------------------------------------
# state.bump_schema_version

def handle_bump_schema_version(action, ctx):
    """Set ``schema_version`` to the given value if strictly greater.

    action keys:
      - to: integer target version (REQUIRED)
    """
    target = action.get("to")
    if target is None:
        return _fail("state.bump_schema_version requires 'to'")
    try:
        target_int = int(target)
    except (TypeError, ValueError):
        return _fail("state.bump_schema_version: 'to' must be integer, got %r" % target)
    client = _resolve_client(ctx)
    current = client.get("schema_version", 0)
    try:
        current_int = int(current or 0)
    except (TypeError, ValueError):
        current_int = 0
    if current_int >= target_int:
        return _ok(False, reason="already_at_or_above",
                   current=current_int, target=target_int)
    if ctx.get("dry_run"):
        return _ok(True, would_bump=True, current=current_int, target=target_int)
    changed = bool(client.set("schema_version", target_int))
    return _ok(changed, current=current_int, target=target_int)
