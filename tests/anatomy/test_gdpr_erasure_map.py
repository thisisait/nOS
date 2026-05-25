"""Anatomy CI gate — GDPR right-to-erasure map + event-whitelist alignment.

C3.4 (2026-05-25) added tasks/gdpr-forget.yml: a dry-run-first Art. 17 erasure
fan-out driven by the audited destructive-command list state/gdpr-erasure-map.yml.
This gate pins the map's integrity (so an erasure can't target a phantom service
or carry a malformed command) and keeps the Bone/Wing event whitelists aligned
(a drift there silently 400s the gdpr_forget_user audit event).
"""

from __future__ import annotations

import pathlib

import pytest
import yaml

# tests/conftest.py adds files/anatomy/ to sys.path.
from module_utils import nos_gdpr  # type: ignore  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[2]
MAP_PATH = REPO / "state" / "gdpr-erasure-map.yml"
PLUGINS_ROOT = REPO / "files" / "anatomy" / "plugins"

VALID_METHODS = {"authentik_api", "container_exec", "manual"}


def _entries() -> list[dict]:
    return yaml.safe_load(MAP_PATH.read_text())["services"]


def _register_ids() -> set[str]:
    return {r["id"] for r in nos_gdpr.records_from_plugins(PLUGINS_ROOT)}


def test_map_loads_with_services():
    entries = _entries()
    assert entries and all(isinstance(e, dict) for e in entries)


def test_ids_unique_and_svc_prefixed():
    ids = [e["id"] for e in _entries()]
    assert len(ids) == len(set(ids)), "duplicate erasure-map id"
    assert all(i.startswith("svc_") for i in ids)


def test_every_map_id_is_a_real_service():
    """An erasure entry must target a service that exists in the register —
    otherwise we'd print a deletion step for a phantom service."""
    reg = _register_ids()
    orphans = [e["id"] for e in _entries() if e["id"] not in reg]
    assert not orphans, f"erasure-map ids with no register/plugin: {orphans}"


def test_exactly_one_authentik_anchor():
    anchors = [e for e in _entries() if e["method"] == "authentik_api"]
    assert [a["id"] for a in anchors] == ["svc_authentik"]


@pytest.mark.parametrize("entry", _entries(), ids=lambda e: e["id"])
def test_entry_is_well_formed(entry):
    assert entry["method"] in VALID_METHODS, entry["method"]
    assert entry.get("flag"), "each entry needs a gate flag (or 'always')"
    assert entry.get("note", "").strip(), "each entry needs an operator-facing note"
    if entry["method"] == "container_exec":
        assert entry.get("stack") and entry.get("service"), \
            "container_exec needs stack + service to resolve the container"
        assert "{{ forget_subject }}" in entry.get("command", ""), \
            "container_exec command must be keyed on the subject email"


def test_forget_event_whitelisted_both_sides():
    """gdpr_forget_user must be in BOTH the Bone and Wing event whitelists."""
    bone = (REPO / "files/anatomy/bone/events.py").read_text()
    wing = (REPO / "files/anatomy/wing/app/Model/EventRepository.php").read_text()
    assert '"gdpr_forget_user"' in bone, "missing from Bone VALID_TYPES"
    assert "'gdpr_forget_user'" in wing, "missing from Wing EventRepository::VALID_TYPES"
