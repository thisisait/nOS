"""Anatomy CI gate — GDPR Art-15 right-of-access EXPORT map + correctness.

Art-15 (right of access) added tasks/gdpr-export.yml: a dry-run-first, READ-ONLY
export fan-out driven by the audited command list state/gdpr-export-map.yml.
Read-only sibling of test_gdpr_erasure_map.py. This gate pins:
  * map integrity (no phantom service, subject-keyed container_exec commands),
  * the per-user-PII coverage set (silent-green loophole closed),
  * access/erasure id-set symmetry (CNIL expects symmetric DSAR coverage),
  * the lawful-basis correctness rule (the analogue of test_gdpr_dsar_status.py's
    overclaiming guard): the run records request_type='access', and any entry
    tagged portability_eligible MUST actually have a consent/contract lawful
    basis in its plugin — so the Art-20 overclaim cannot be re-introduced,
  * READ-ONLY-by-construction (no mutating verb in any container_exec command),
  * Bone/Wing event-whitelist alignment (a drift silently 400s gdpr_export_user).
"""

from __future__ import annotations

import pathlib

import pytest
import yaml

# tests/conftest.py adds files/anatomy/ to sys.path.
from module_utils import nos_gdpr  # type: ignore  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[2]
MAP_PATH = REPO / "state" / "gdpr-export-map.yml"
ERASURE_PATH = REPO / "state" / "gdpr-erasure-map.yml"
PLUGINS_ROOT = REPO / "files" / "anatomy" / "plugins"
EXPORT_TASK = REPO / "tasks" / "gdpr-export.yml"

VALID_METHODS = {"authentik_api", "container_exec", "manual"}
PORTABILITY_BASES = {"consent", "contract"}
# Mutating-verb denylist — locks the map's "READ-ONLY by construction" claim
# into CI so a future edit can't turn an auto-run export into a destructive op.
MUTATING_TOKENS = (
    " delete", " rm ", " remove", " drop", " purge", " destroy",
    " --yes", " update ", " set ", " create ", " insert ",
)
# Keep this residual set in sync with test_gdpr_erasure_map.py
# (test_backend_store_residual_reach_documented). These backend/derived stores
# are reached by Art-17 erasure but NOT extracted by an Art-15 access export.
RESIDUAL_STORES = {"svc_redis", "svc_qdrant", "svc_rustfs", "svc_wing", "svc_loki", "svc_tempo"}


def _entries() -> list[dict]:
    return yaml.safe_load(MAP_PATH.read_text())["services"]


def _register_ids() -> set[str]:
    return {r["id"] for r in nos_gdpr.records_from_plugins(PLUGINS_ROOT)}


def _plugin_legal_basis(svc_id: str) -> str | None:
    """Lawful basis for a svc_<name> id from its plugin gdpr block (anchors
    svc_authentik / svc_bluesky-pds have no per-service consent/contract basis
    -> None, i.e. access-only)."""
    name = svc_id.removeprefix("svc_")
    p = PLUGINS_ROOT / f"{name}-base" / "plugin.yml"
    if not p.is_file():
        return None
    d = yaml.safe_load(p.read_text()) or {}
    return (d.get("gdpr") or {}).get("legal_basis")


def test_map_loads_with_services():
    entries = _entries()
    assert entries and all(isinstance(e, dict) for e in entries)


def test_ids_unique_and_svc_prefixed():
    ids = [e["id"] for e in _entries()]
    assert len(ids) == len(set(ids)), "duplicate export-map id"
    assert all(i.startswith("svc_") for i in ids)


def test_every_map_id_is_a_real_service():
    reg = _register_ids()
    orphans = [e["id"] for e in _entries() if e["id"] not in reg]
    assert not orphans, f"export-map ids with no register/plugin: {orphans}"


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
        cmd = entry.get("command", "")
        assert "{{ export_subject }}" in cmd, \
            "container_exec command must be keyed on the export subject email"
        low = " " + cmd.lower() + " "
        hits = [t for t in MUTATING_TOKENS if t in low]
        assert not hits, (
            f"container_exec command for {entry['id']} contains a mutating verb "
            f"{hits} — exports MUST be read-only by construction"
        )


def test_portability_eligible_matches_lawful_basis():
    """Overclaiming guard (analogue of test_gdpr_dsar_status.py): an entry may
    be tagged portability_eligible ONLY if its plugin's lawful basis is
    consent/contract — Art-20 does not exist for legitimate_interests. And the
    converse: every consent/contract service MUST carry the tag, so a new
    portable service can't silently lose its Art-20 marking."""
    for e in _entries():
        basis = _plugin_legal_basis(e["id"])
        tagged = bool(e.get("portability_eligible", False))
        if tagged:
            assert basis in PORTABILITY_BASES, (
                f"{e['id']} is portability_eligible but lawful_basis={basis!r} "
                "— Art-20 portability requires consent/contract"
            )
        elif basis in PORTABILITY_BASES:
            raise AssertionError(
                f"{e['id']} has lawful_basis={basis!r} (portable) but is NOT "
                "tagged portability_eligible — add the flag"
            )


def test_run_records_access_not_portability():
    """The DSAR row request_type is the universally-valid 'access', never the
    false 'portability' on a legitimate-interests store."""
    src = EXPORT_TASK.read_text()
    assert "'request_type': 'access'" in src, \
        "intake must record request_type='access' (the always-valid right)"
    assert "'request_type': 'portability'" not in src, \
        "must not blanket-record 'portability' — 18/21 services run on legitimate_interests"


def test_authentik_executor_writes_single_match_not_envelope():
    """Cross-subject-leak guard: write the single exact-email-match user, never
    the raw multi-user ?email= results envelope."""
    src = EXPORT_TASK.read_text()
    assert "selectattr('email', 'equalto', export_subject)" in src, \
        "Authentik export must select the single exact-email match"
    assert "_ak_user.json | to_nice_json" not in src, \
        "must NOT serialize the whole results envelope into the subject's bundle"


def _inscope_expected() -> set[str]:
    """Every per-user-PII service that MUST carry an Art-15 export entry: gdpr
    plugins with authentik.mode in {native_oidc, header_oidc} plus the AT-proto
    (svc_bluesky-pds) + authentik anchors. Byte-for-byte the erasure-map's
    in-scope set (21 service plugins + 2 anchors = 23) — access mirrors erasure.
    forward_auth services are access gates with no per-user state -> out of scope."""
    ids = {"svc_authentik", "svc_bluesky-pds"}
    for f in PLUGINS_ROOT.glob("*/plugin.yml"):
        d = yaml.safe_load(f.read_text()) or {}
        a = d.get("authentik") or {}
        if a.get("mode") in ("native_oidc", "header_oidc") and d.get("gdpr"):
            ids.add("svc_" + f.parent.name.removesuffix("-base"))
    return ids


def test_every_per_user_pii_service_has_export_entry():
    """Coverage-completeness: a new native/header_oidc service can't ship with
    NO export path while the gate stays green. No programmatic export -> still
    needs an entry (method:manual + note) = the documented-deferral mechanism."""
    mapped = {e["id"] for e in _entries()}
    missing = sorted(_inscope_expected() - mapped)
    assert not missing, (
        "per-user-PII services with NO Art-15 export entry — add each to "
        "state/gdpr-export-map.yml (method:manual + note if no read-only "
        f"email-keyed export is verified yet): {missing}"
    )


def test_export_in_scope_matches_erasure_in_scope():
    """Access (Art-15) and erasure (Art-17) cover the SAME per-user-PII set.
    Guards drift where a service gains an erasure path but no export path (or
    vice-versa). Keep RESIDUAL_STORES in sync with test_gdpr_erasure_map.py."""
    e_ids = {e["id"] for e in yaml.safe_load(ERASURE_PATH.read_text())["services"]}
    export_ids = {e["id"] for e in _entries()}
    assert (e_ids - RESIDUAL_STORES) == export_ids, (
        "export/erasure per-user-PII coverage diverged: "
        f"only-erasure={sorted((e_ids - RESIDUAL_STORES) - export_ids)}, "
        f"only-export={sorted(export_ids - (e_ids - RESIDUAL_STORES))}"
    )


def test_export_event_whitelisted_both_sides():
    """gdpr_export_user must be in BOTH the Bone and Wing event whitelists."""
    bone = (REPO / "files/anatomy/bone/events.py").read_text()
    wing = (REPO / "files/anatomy/wing/app/Model/EventRepository.php").read_text()
    assert '"gdpr_export_user"' in bone, "missing from Bone VALID_TYPES"
    assert "'gdpr_export_user'" in wing, "missing from Wing EventRepository::VALID_TYPES"
