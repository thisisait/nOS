"""Coexistence endpoints — list, provision, cutover, cleanup.

State of truth is ~/.nos/state.yml `coexistence` block. Mutations go through
the Ansible `nos_coexistence` module (agent 5), invoked via ansible-playbook
with specific tags.
"""

from __future__ import annotations

import re
from typing import Any

import migrations as migrate_mod  # sibling module in ~/bone/
import state as state_mod

_SERVICE_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_TAG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def list_tracks() -> dict[str, Any]:
    state = state_mod.read_state()
    block = state.get("coexistence")
    if not isinstance(block, dict):
        return {"services": {}}

    out: dict[str, list[dict[str, Any]]] = {}
    for svc, svc_block in block.items():
        if not isinstance(svc_block, dict):
            continue
        active = svc_block.get("active_track")
        tracks = svc_block.get("tracks") or []
        rows: list[dict[str, Any]] = []
        for t in tracks:
            if not isinstance(t, dict):
                continue
            row = dict(t)
            row["active"] = (row.get("tag") == active)
            rows.append(row)
        out[svc] = rows
    return {"services": out}


def _validate(service: str, tag: str | None = None) -> str | None:
    if not _SERVICE_RE.match(service):
        return "invalid service name"
    if tag is not None and not _TAG_RE.match(tag):
        return "invalid tag"
    return None


def provision(service: str, body: dict[str, Any]) -> dict[str, Any]:
    tag = str(body.get("tag", ""))
    version = str(body.get("version", ""))
    err = _validate(service, tag)
    if err is not None:
        return {"error": err, "status": 400}
    if not _VERSION_RE.match(version):
        return {"error": "invalid version", "status": 400}

    extra = {
        "coexist_service": service,
        "coexist_tag": tag,
        "coexist_version": version,
    }
    if "port" in body and body["port"]:
        port = str(body["port"])
        if not port.isdigit() or not (1 <= int(port) <= 65535):
            return {"error": "invalid port", "status": 400}
        extra["coexist_port"] = port
    if "data_source" in body and body["data_source"]:
        ds = str(body["data_source"])
        if not re.match(r"^(empty|clone_from:[a-z0-9_-]{1,32})$", ds):
            return {"error": "invalid data_source", "status": 400}
        extra["coexist_data_source"] = ds

    result = migrate_mod.invoke_playbook("coexist-provision", extra)
    return {"service": service, "tag": tag, **result}


def cutover(service: str, target_tag: str) -> dict[str, Any]:
    err = _validate(service, target_tag)
    if err is not None:
        return {"error": err, "status": 400}
    result = migrate_mod.invoke_playbook(
        "coexist-cutover",
        {"coexist_service": service, "coexist_tag": target_tag},
    )
    return {"service": service, "target_tag": target_tag, **result}


def cleanup(service: str, tag: str, force: bool = False) -> dict[str, Any]:
    err = _validate(service, tag)
    if err is not None:
        return {"error": err, "status": 400}
    extra: dict[str, str] = {
        "coexist_service": service,
        "coexist_tag": tag,
    }
    if force:
        extra["coexist_force"] = "true"
    result = migrate_mod.invoke_playbook("coexist-cleanup", extra)
    return {"service": service, "tag": tag, "force": force, **result}
