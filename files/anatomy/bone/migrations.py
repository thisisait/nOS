"""Migration endpoints — list, preview, apply, rollback.

Apply / rollback shell out to ansible-playbook (same pattern as the existing
`/api/run-tag` endpoint in main.py). Extra-vars supply the migration id so
the pre-migrate orchestrator can target it.

Spec: framework-plan.md section 4.2 (action table) + section 5.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any

import yaml

import state as state_mod  # sibling module in ~/bone/

MIGRATIONS_DIR = Path(
    os.getenv("NOS_MIGRATIONS_DIR",
              os.path.join(os.path.expanduser("~/nOS"), "migrations"))
)
PLAYBOOK_DIR = Path(os.getenv("PLAYBOOK_DIR", os.path.expanduser("~/nOS")))

# Migration ids look like "2026-04-22-rebrand-foo". Restrict to keep shell
# invocations safe — ansible extra-vars are always shell-parsed.
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")


def _load_migration_file(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(data, dict) or "id" not in data:
        return None
    return data


def list_on_disk() -> list[dict[str, Any]]:
    """Every migrations/*.yml parsed into a record."""
    if not MIGRATIONS_DIR.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for p in sorted(MIGRATIONS_DIR.glob("*.yml")):
        if p.name.startswith("_"):
            continue
        rec = _load_migration_file(p)
        if rec is None:
            continue
        rec["_source_path"] = str(p)
        out.append(rec)
    return out


def applied_from_state() -> list[dict[str, Any]]:
    s = state_mod.read_state()
    ma = s.get("migrations_applied")
    return ma if isinstance(ma, list) else []


def split_pending_applied() -> dict[str, list[dict[str, Any]]]:
    """Merge on-disk migrations with state-tracked applied history."""
    applied = applied_from_state()
    applied_ids = {str(m.get("id")) for m in applied}
    on_disk = list_on_disk()
    pending = [m for m in on_disk if m.get("id") not in applied_ids]
    return {"pending": pending, "applied": applied, "on_disk": on_disk}


def get_by_id(migration_id: str) -> dict[str, Any] | None:
    if not _ID_RE.match(migration_id):
        return None
    for rec in list_on_disk():
        if rec.get("id") == migration_id:
            applied = applied_from_state()
            for a in applied:
                if a.get("id") == migration_id:
                    rec["_applied"] = a
                    break
            return rec
    return None


def validate_id(migration_id: str) -> bool:
    return bool(_ID_RE.match(migration_id))


def invoke_playbook(tag: str, extra_vars: dict[str, str], timeout: int = 1800
                    ) -> dict[str, Any]:
    """Run ansible-playbook with the given tag + extra-vars. Returns a dict
    shaped like the existing run-tag response.
    """
    # Build extra-vars safely: only allow [A-Za-z0-9_.-] in keys/values since
    # this goes onto the ansible CLI. Keys may include underscores; values
    # should already be pre-validated migration ids / recipe ids.
    safe_pairs: list[str] = []
    for k, v in extra_vars.items():
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", k):
            raise ValueError(f"Invalid extra-var key: {k}")
        if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$", str(v)):
            raise ValueError(f"Invalid extra-var value: {v}")
        safe_pairs.append(f"{k}={v}")

    cmd = [
        "ansible-playbook", "main.yml",
        "--tags", tag,
    ]
    if safe_pairs:
        cmd += ["--extra-vars", " ".join(safe_pairs)]

    proc = subprocess.Popen(
        cmd,
        cwd=str(PLAYBOOK_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        stdout, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        return {"returncode": -1, "timeout": True, "output": ""}

    return {
        "returncode": proc.returncode,
        "output": stdout[-8000:] if len(stdout) > 8000 else stdout,
    }


def preview(migration_id: str) -> dict[str, Any]:
    """Dry-run path — invokes the migrate tag with dry_run=true."""
    if not validate_id(migration_id):
        return {"error": "invalid migration id", "status": 400}
    rec = get_by_id(migration_id)
    if rec is None:
        return {"error": "migration not found", "status": 404}
    result = invoke_playbook(
        "migrate",
        {"migration_id": migration_id, "migrate_dry_run": "true"},
        timeout=600,
    )
    return {"migration_id": migration_id, "preview": True, **result}


def apply(migration_id: str, dry_run: bool = False) -> dict[str, Any]:
    if not validate_id(migration_id):
        return {"error": "invalid migration id", "status": 400}
    rec = get_by_id(migration_id)
    if rec is None:
        return {"error": "migration not found", "status": 404}
    extra = {"migration_id": migration_id}
    if dry_run:
        extra["migrate_dry_run"] = "true"
    result = invoke_playbook("migrate", extra)
    return {"migration_id": migration_id, "applied": not dry_run, **result}


def rollback(migration_id: str) -> dict[str, Any]:
    if not validate_id(migration_id):
        return {"error": "invalid migration id", "status": 400}
    rec = get_by_id(migration_id)
    if rec is None:
        return {"error": "migration not found", "status": 404}
    result = invoke_playbook(
        "migrate-rollback",
        {"migration_id": migration_id},
    )
    return {"migration_id": migration_id, "rolled_back": True, **result}
