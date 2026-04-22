"""Shared helpers for nOS state read/write + manifest introspection.

Used by ``library/nos_state.py`` and available to other nOS custom modules that
need to read the persisted state (e.g. ``nos_migrate``, ``nos_authentik``).

Design notes
------------
- YAML only, single-file (``~/.nos/state.yml``). No DB.
- ``load_state`` tolerates missing file -> returns bootstrap skeleton.
- Writes are atomic: write to ``<path>.tmp`` then os.replace to ``<path>``.
- Deep merge is used for action="write" with ``merge=True`` so pre-existing
  sections survive partial writes from different plays.
- Version introspection never fails the caller — unreachable docker or missing
  role var returns ``installed=null, healthy=null``.
"""

from __future__ import annotations

import copy
import datetime as _dt
import json
import os
import shutil
import subprocess
import tempfile
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    import yaml  # PyYAML
except Exception:  # pragma: no cover — import error surfaces in module
    yaml = None  # type: ignore[assignment]


DEFAULT_STATE_PATH = "~/.nos/state.yml"
CURRENT_SCHEMA_VERSION = 1
GENERATOR_ID = "pazny.state_manager v1.0"


# ---------------------------------------------------------------------------
# Path & IO helpers
# ---------------------------------------------------------------------------

def expand_path(path: str) -> str:
    """Expand ~ and environment variables, return absolute path."""
    return os.path.abspath(os.path.expanduser(os.path.expandvars(path)))


def utcnow_iso() -> str:
    """ISO-8601 UTC timestamp with 'Z' suffix, second precision."""
    return _dt.datetime.now(tz=_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _require_yaml() -> None:
    if yaml is None:
        raise RuntimeError("PyYAML is required for nos_state_lib (pip install pyyaml).")


def empty_state() -> Dict[str, Any]:
    """Return the bootstrap skeleton used when state.yml does not exist.

    The skeleton conforms to state.schema.json with the minimum required keys.
    Callers may overlay additional data via deep_merge.
    """
    return {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "generated_at": utcnow_iso(),
        "generator": GENERATOR_ID,
        "instance": {"name": "nos"},
        "services": {},
        "migrations_applied": [],
        "upgrades_applied": [],
    }


def load_state(state_path: str = DEFAULT_STATE_PATH) -> Dict[str, Any]:
    """Load ~/.nos/state.yml. Returns empty skeleton if file is missing.

    Never raises on missing file — graceful degradation is a hard requirement
    (agent brief). On malformed YAML this does raise, since silent data loss
    would be worse than a loud failure.
    """
    _require_yaml()
    full = expand_path(state_path)
    if not os.path.exists(full):
        return empty_state()
    with open(full, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if data is None:
        return empty_state()
    if not isinstance(data, dict):
        raise ValueError(
            f"state file {full!r} must contain a YAML mapping at the top level"
        )
    return data


def dump_state(state: Dict[str, Any], state_path: str = DEFAULT_STATE_PATH) -> str:
    """Atomically write state to disk. Creates parent dir (0700) as needed.

    Returns the absolute path written.
    """
    _require_yaml()
    full = expand_path(state_path)
    parent = os.path.dirname(full)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, mode=0o700, exist_ok=True)

    fd, tmp = tempfile.mkstemp(
        prefix=".state-",
        suffix=".tmp",
        dir=parent or None,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            yaml.safe_dump(
                state,
                fh,
                sort_keys=False,
                default_flow_style=False,
                allow_unicode=True,
            )
        os.chmod(tmp, 0o600)
        os.replace(tmp, full)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return full


# ---------------------------------------------------------------------------
# Deep merge + dotted-path get/set
# ---------------------------------------------------------------------------

def deep_merge(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    """Recursive dict merge. ``overlay`` wins at leaf collisions.

    Lists are replaced wholesale (not concatenated) — predictable for callers.
    A new dict is returned; inputs are not mutated.
    """
    out = copy.deepcopy(base)
    _merge_inplace(out, overlay)
    return out


def _merge_inplace(dst: Dict[str, Any], src: Dict[str, Any]) -> None:
    for k, v in src.items():
        if (
            k in dst
            and isinstance(dst[k], dict)
            and isinstance(v, dict)
        ):
            _merge_inplace(dst[k], v)
        else:
            dst[k] = copy.deepcopy(v)


def dotted_get(state: Dict[str, Any], path: str, default: Any = None) -> Any:
    """Return value at dotted path (``services.grafana.installed``)."""
    node: Any = state
    for part in path.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return default
    return node


def dotted_set(state: Dict[str, Any], path: str, value: Any) -> bool:
    """Set value at dotted path, creating intermediate dicts as needed.

    Returns True if the value actually changed (idempotency hook).
    """
    parts = path.split(".")
    cursor = state
    for part in parts[:-1]:
        nxt = cursor.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cursor[part] = nxt
        cursor = nxt
    prev = cursor.get(parts[-1], _SENTINEL)
    if prev == value:
        return False
    cursor[parts[-1]] = value
    return True


def dotted_unset(state: Dict[str, Any], path: str) -> bool:
    """Delete the key at dotted path. Returns True if something was removed."""
    parts = path.split(".")
    cursor = state
    for part in parts[:-1]:
        nxt = cursor.get(part) if isinstance(cursor, dict) else None
        if not isinstance(nxt, dict):
            return False
        cursor = nxt
    if isinstance(cursor, dict) and parts[-1] in cursor:
        del cursor[parts[-1]]
        return True
    return False


_SENTINEL = object()


# ---------------------------------------------------------------------------
# Manifest loading + introspection
# ---------------------------------------------------------------------------

def load_manifest(manifest_path: str) -> Dict[str, Any]:
    _require_yaml()
    full = expand_path(manifest_path)
    with open(full, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"manifest {full!r} must be a YAML mapping")
    data.setdefault("services", [])
    return data


def _which(cmd: str) -> Optional[str]:
    return shutil.which(cmd)


def _run(cmd: List[str], timeout: int = 10) -> Tuple[int, str, str]:
    """Subprocess helper. Never raises — returns (rc, stdout, stderr)."""
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        return 127, "", str(exc)


def introspect_docker_image(container_name: str) -> Optional[str]:
    """Return the image tag of a running (or stopped) container, or None.

    Prefers ``docker inspect -f {{.Config.Image}}``; falls back to None on any
    failure (container not present, docker CLI missing, socket unreachable).
    """
    if not _which("docker"):
        return None
    rc, out, _err = _run(
        ["docker", "inspect", "-f", "{{.Config.Image}}", container_name],
        timeout=5,
    )
    if rc != 0:
        return None
    image = out.strip()
    if not image:
        return None
    # Return just the tag portion if present.
    if ":" in image.rsplit("/", 1)[-1]:
        return image.rsplit(":", 1)[1]
    return image


def introspect_docker_running(container_name: str) -> Optional[bool]:
    if not _which("docker"):
        return None
    rc, out, _err = _run(
        ["docker", "inspect", "-f", "{{.State.Running}}", container_name],
        timeout=5,
    )
    if rc != 0:
        return None
    return out.strip().lower() == "true"


def introspect_brew_version(formula: str) -> Optional[str]:
    if not _which("brew"):
        return None
    rc, out, _err = _run(["brew", "list", "--versions", formula], timeout=10)
    if rc != 0:
        return None
    parts = out.strip().split()
    if len(parts) >= 2:
        return parts[1]
    return None


def introspect_launchd_loaded(label: str) -> Optional[bool]:
    if not _which("launchctl"):
        return None
    rc, out, _err = _run(["launchctl", "list"], timeout=5)
    if rc != 0:
        return None
    for line in out.splitlines():
        cols = line.split()
        if cols and cols[-1] == label:
            return True
    return False


def introspect_service(
    svc: Dict[str, Any],
    role_vars: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return the state entry for one manifest service.

    role_vars: optional mapping of role default vars (e.g. {"grafana_version":
    "11.5.0"}) — used to populate 'desired' and resolve {{ var }} substitutions
    in lightweight template fields. The full Jinja pipeline is the Ansible
    task's job; this function only needs enough to report desired version.
    """
    role_vars = role_vars or {}
    version_source = svc.get("version_source") or "none"
    entry: Dict[str, Any] = {
        "installed": None,
        "desired": None,
        "data_path": None,
        "healthy": None,
        "enabled": None,
        "stack": svc.get("stack"),
        "category": svc.get("category"),
    }

    version_var = svc.get("version_var")
    if version_var and version_var in role_vars:
        entry["desired"] = role_vars[version_var]

    data_path_var = svc.get("data_path_var")
    if data_path_var and data_path_var in role_vars:
        entry["data_path"] = role_vars[data_path_var]

    install_flag = svc.get("install_flag")
    if install_flag and install_flag in role_vars:
        entry["enabled"] = bool(role_vars[install_flag])

    if version_source == "docker_image":
        container = svc.get("container_name")
        if container:
            installed = introspect_docker_image(container)
            entry["installed"] = installed
            running = introspect_docker_running(container)
            if running is not None:
                entry["healthy"] = running
    elif version_source == "homebrew":
        formula = svc.get("brew_formula") or svc.get("id")
        entry["installed"] = introspect_brew_version(formula)
        entry["healthy"] = entry["installed"] is not None
    elif version_source == "launchd":
        label = svc.get("launchd_label")
        if label:
            loaded = introspect_launchd_loaded(label)
            entry["healthy"] = loaded
            # launchd has no version concept; surface "loaded" as a token.
            entry["installed"] = "loaded" if loaded else None
    elif version_source == "git_tag":
        # Best-effort git describe against project root (passed via role_vars).
        project = role_vars.get("playbook_dir")
        if project and _which("git"):
            rc, out, _ = _run(
                ["git", "-C", project, "describe", "--tags", "--always"],
                timeout=5,
            )
            if rc == 0:
                entry["installed"] = out.strip() or None
    # version_source in {"pm2", "pip", "npm", "none", "custom"}: introspect is
    # a no-op (agents can extend per-service later).

    return entry


def introspect_all(
    manifest: Dict[str, Any],
    role_vars: Optional[Dict[str, Any]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Run introspect_service for every manifest service, keyed by id."""
    out: Dict[str, Dict[str, Any]] = {}
    for svc in manifest.get("services", []):
        sid = svc.get("id")
        if not sid:
            continue
        out[sid] = introspect_service(svc, role_vars=role_vars)
    return out


# ---------------------------------------------------------------------------
# JSON-safe serialization (for Ansible return payloads)
# ---------------------------------------------------------------------------

def to_json_safe(obj: Any) -> Any:
    """Recursively convert YAML-loaded structures into JSON-serializable ones."""
    if isinstance(obj, dict):
        return {str(k): to_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_json_safe(v) for v in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    if isinstance(obj, _dt.datetime):
        return obj.strftime("%Y-%m-%dT%H:%M:%SZ")
    return json.loads(json.dumps(obj, default=str))


__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "DEFAULT_STATE_PATH",
    "GENERATOR_ID",
    "deep_merge",
    "dotted_get",
    "dotted_set",
    "dotted_unset",
    "dump_state",
    "empty_state",
    "expand_path",
    "introspect_all",
    "introspect_brew_version",
    "introspect_docker_image",
    "introspect_docker_running",
    "introspect_launchd_loaded",
    "introspect_service",
    "load_manifest",
    "load_state",
    "to_json_safe",
    "utcnow_iso",
]
