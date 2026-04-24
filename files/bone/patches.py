"""Patch endpoints — list, plan, apply.

Patches are developer-authored code remediations persisted as YAML recipes in
``patches/*.yml`` (one file per patch id, PATCH-NNN). The on-disk file is the
source of truth for *what* the patch does; ``patches_applied`` in the Wing
SQLite is the read-mirror of *where* each patch has already been applied.

Apply / plan shell out to ``ansible-playbook --tags apply-patches``; the
``apply-patches.yml`` orchestrator loads the YAML, dispatches each step through
the ``nos_patch_actions`` table (see module_utils), and emits patch_* events
(see EventRepository::VALID_TYPES) via the callback plugin.

Mirrors ``upgrades.py`` in shape so Wing's PatchesPresenter can proxy
cleanly.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

import migrations as migrate_mod  # sibling module — reuses invoke_playbook()

PATCHES_DIR = Path(
    os.getenv(
        "NOS_PATCHES_DIR",
        os.path.join(os.path.expanduser("~/nOS"), "patches"),
    )
)

# PATCH-NNN or PATCH-NNNN style ids. Kept strict so we can inject this value
# onto the ansible-playbook CLI without shell-escaping concerns.
_ID_RE = re.compile(r"^PATCH-[0-9]{3,5}$")


def _load_patch_file(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(data, dict) or not data.get("id"):
        return None
    data["_source_path"] = str(path)
    return data


def list_on_disk() -> list[dict[str, Any]]:
    """Every patches/*.yml parsed into a record, sorted by id."""
    if not PATCHES_DIR.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for p in sorted(PATCHES_DIR.glob("*.yml")):
        if p.name.startswith("_"):
            continue
        rec = _load_patch_file(p)
        if rec is None:
            continue
        out.append(rec)
    return out


def list_all() -> dict[str, Any]:
    """Summary matrix for /api/patches. Separate from Wing's DB list —
    this enumerates what's authored *on disk* (the apply surface)."""
    return {"patches": list_on_disk()}


def get_by_id(patch_id: str) -> dict[str, Any] | None:
    if not _ID_RE.match(patch_id):
        return None
    path = PATCHES_DIR / f"{patch_id}.yml"
    if not path.is_file():
        return None
    return _load_patch_file(path)


def validate_id(patch_id: str) -> bool:
    return bool(_ID_RE.match(patch_id))


def _not_found() -> dict[str, Any]:
    return {"error": "patch not found", "status": 404}


def plan(patch_id: str) -> dict[str, Any]:
    """Dry-run path — ansible-playbook --tags apply-patches with patch_dry_run=true."""
    if not validate_id(patch_id):
        return {"error": "invalid patch id", "status": 400}
    rec = get_by_id(patch_id)
    if rec is None:
        return _not_found()
    result = migrate_mod.invoke_playbook(
        "apply-patches",
        {"patch_id": patch_id, "patch_dry_run": "true"},
        timeout=600,
    )
    return {"patch_id": patch_id, "plan": True, **result}


def apply(patch_id: str) -> dict[str, Any]:
    """Real-apply path — identical to plan() but without dry_run."""
    if not validate_id(patch_id):
        return {"error": "invalid patch id", "status": 400}
    rec = get_by_id(patch_id)
    if rec is None:
        return _not_found()
    result = migrate_mod.invoke_playbook(
        "apply-patches",
        {"patch_id": patch_id},
    )
    return {"patch_id": patch_id, "applied": True, **result}
