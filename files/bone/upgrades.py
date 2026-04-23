"""Upgrade endpoints — matrix, recipes, plan, apply.

Recipes live in `upgrades/*.yml` (one file per service, authored by agent 6).
Apply shells out to ansible-playbook --tags upgrade.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

import migrations as migrate_mod  # sibling module in ~/boxapi/
import state as state_mod

UPGRADES_DIR = Path(
    os.getenv("NOS_UPGRADES_DIR",
              os.path.join(os.path.expanduser("~/nOS"), "upgrades"))
)

_SERVICE_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_RECIPE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")


def _load_service_file(service: str) -> dict[str, Any] | None:
    if not _SERVICE_RE.match(service):
        return None
    path = UPGRADES_DIR / f"{service}.yml"
    if not path.is_file():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(data, dict):
        return None
    data["_source_path"] = str(path)
    return data


def all_service_files() -> list[dict[str, Any]]:
    if not UPGRADES_DIR.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for p in sorted(UPGRADES_DIR.glob("*.yml")):
        if p.name.startswith("_"):
            continue
        try:
            with p.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(data, dict) or not data.get("service"):
            continue
        data["_source_path"] = str(p)
        out.append(data)
    return out


def matrix() -> dict[str, Any]:
    """For each service with a recipe file, produce an installed-vs-available row."""
    state = state_mod.read_state()
    services_state = state_mod.get_services(state)
    rows: list[dict[str, Any]] = []

    for svc_doc in all_service_files():
        svc_id = svc_doc["service"]
        svc_state = services_state.get(svc_id, {}) if isinstance(services_state, dict) else {}
        installed = svc_state.get("installed")
        recipes = svc_doc.get("recipes") or []

        # Pick the first recipe whose from_regex matches installed.
        matching = None
        for r in recipes:
            if not isinstance(r, dict):
                continue
            rx = r.get("from_regex")
            if installed and rx:
                try:
                    if re.match(rx, str(installed)):
                        matching = r
                        break
                except re.error:
                    continue

        upgrade_avail = svc_state.get("upgrade_available") or {}
        rows.append({
            "id": svc_id,
            "installed": installed,
            "stable": upgrade_avail.get("version"),
            "latest": upgrade_avail.get("version"),
            "severity": (matching or {}).get("severity")
                        or upgrade_avail.get("severity"),
            "recipe_available": matching is not None,
            "recipe_id": (matching or {}).get("id"),
            "docs_url": svc_doc.get("docs_url"),
        })

    return {"services": rows}


def for_service(service: str) -> dict[str, Any] | None:
    return _load_service_file(service)


def get_recipe(service: str, recipe_id: str) -> dict[str, Any] | None:
    if not _RECIPE_RE.match(recipe_id):
        return None
    doc = _load_service_file(service)
    if doc is None:
        return None
    for r in doc.get("recipes", []) or []:
        if isinstance(r, dict) and r.get("id") == recipe_id:
            return {"service": service, "recipe": r, "docs_url": doc.get("docs_url")}
    return None


def _validate(service: str, recipe_id: str) -> str | None:
    if not _SERVICE_RE.match(service):
        return "invalid service"
    if not _RECIPE_RE.match(recipe_id):
        return "invalid recipe id"
    if get_recipe(service, recipe_id) is None:
        return "recipe not found"
    return None


def plan(service: str, recipe_id: str) -> dict[str, Any]:
    err = _validate(service, recipe_id)
    if err is not None:
        return {"error": err, "status": 400 if err != "recipe not found" else 404}
    result = migrate_mod.invoke_playbook(
        "upgrade",
        {
            "upgrade_service": service,
            "upgrade_recipe_id": recipe_id,
            "upgrade_dry_run": "true",
        },
        timeout=600,
    )
    return {"service": service, "recipe_id": recipe_id, "plan": True, **result}


def apply(service: str, recipe_id: str) -> dict[str, Any]:
    err = _validate(service, recipe_id)
    if err is not None:
        return {"error": err, "status": 400 if err != "recipe not found" else 404}
    result = migrate_mod.invoke_playbook(
        "upgrade",
        {"upgrade_service": service, "upgrade_recipe_id": recipe_id},
    )
    return {"service": service, "recipe_id": recipe_id, "applied": True, **result}
