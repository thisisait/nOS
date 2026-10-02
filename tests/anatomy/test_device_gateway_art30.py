"""Device gateway Art-30: the register row is the deploy gate, and it is honest.

The gateway was ON in the operator's config with no Art-30 row (2026-10-02).
This pins: a complete gdpr block in device-gateway-base; the converge refuses
install_device_gateway without it; DSAR maps carry the service; the pairing
table has no forbidden column; a writer cannot land without a retention job.
Policy: docs/compliance/devices.md.
"""
from __future__ import annotations

import pathlib
import re

import yaml

from module_utils.nos_app_parser import GDPR_LEGAL_BASES, REQUIRED_GDPR  # type: ignore

REPO = pathlib.Path(__file__).resolve().parents[2]
PLUGIN = REPO / "files/anatomy/plugins/device-gateway-base/plugin.yml"
TABLE = REPO / "state/keap-tables/device-client.table.yml"
GATEWAY = REPO / "files/anatomy/device-gateway/gateway.py"
MAIN = REPO / "main.yml"
DOC = REPO / "docs/compliance/devices.md"
ERASURE = REPO / "state/gdpr-erasure-map.yml"
EXPORT = REPO / "state/gdpr-export-map.yml"
REGISTER = REPO / "state/dpa-register.md"

# A column on device-client named like any of these is data the policy forbids.
FORBIDDEN_COLUMN_RE = re.compile(
    r"(serial|imei|udid|mac|advertising|location|gps|lat|lon|audio|voice|"
    r"transcript|message|contact|photo|health|biometric|token|secret|password|ip)",
    re.I,
)
WRITER_RE = re.compile(r'method="(POST|PUT|PATCH|DELETE)"')


def _plugin() -> dict:
    return yaml.safe_load(PLUGIN.read_text(encoding="utf-8")) or {}


def gdpr_block_is_complete(gdpr: dict) -> list[str]:
    """The app parser's REQUIRED_GDPR + enum, applied to a plugin block."""
    errs = [f"gdpr.{k} missing" for k in REQUIRED_GDPR if k not in gdpr]
    if gdpr.get("legal_basis") not in GDPR_LEGAL_BASES:
        errs.append(f"legal_basis {gdpr.get('legal_basis')!r} not in enum")
    if not str(gdpr.get("purpose", "")).strip():
        errs.append("purpose empty")
    if gdpr.get("retention_days") in (None, 0):
        errs.append("retention_days must be a named horizon (not 0)")
    return errs


def forbidden_columns(table: dict) -> list[str]:
    keys = [c["key"] for c in table["schema"]["columns"]]
    return [k for k in keys if FORBIDDEN_COLUMN_RE.search(k)]


def retention_is_honest(gateway_src: str, plugin: dict) -> tuple[bool, str]:
    """No writer -> the register must say not enforced. Writer -> a Pulse job."""
    jobs = ((plugin.get("pulse") or {}).get("jobs")) or []
    has_job = any(j.get("name") == "device-client-retention" for j in jobs)
    if WRITER_RE.search(gateway_src):
        return has_job, "gateway writes rows but declares no device-client-retention job"
    note = str((plugin.get("gdpr") or {}).get("notes", ""))
    return "retention_enforced: false" in note, "no writer, so the note must say retention_enforced: false"


def test_plugin_carries_a_complete_art30_block():
    assert PLUGIN.is_file(), "device-gateway-base/plugin.yml is the Art-30 row"
    p = _plugin()
    assert gdpr_block_is_complete(p.get("gdpr") or {}) == []
    assert (p.get("requires") or {}).get("feature_flag") == "install_device_gateway"
    assert "end_users" in p["gdpr"]["data_subjects"], "devices belong to users, not operators only"
    assert "authentik" not in p, "the RFC 8628 client is device_gateway.tf, not an authentik: block"


def test_the_gate_is_red_on_an_empty_block():
    assert gdpr_block_is_complete({}) and gdpr_block_is_complete({"legal_basis": "vibes"})
    assert "retention_days" in " ".join(gdpr_block_is_complete({**_plugin()["gdpr"], "retention_days": 0}))


def test_converge_refuses_the_flag_without_the_block():
    tasks = yaml.safe_load(MAIN.read_text(encoding="utf-8"))[0]["tasks"]
    names = [t.get("name", "") for t in tasks]
    gate = next(i for i, n in enumerate(names) if n.startswith("[Art-30] Refuse the device gateway"))
    role = next(i for i, n in enumerate(names) if n == "Device gateway (pazny.device_gateway role)")
    assert gate < role, "the assert must run before the role import"
    t = tasks[gate]
    assert "install_device_gateway" in str(t["when"])
    that = " ".join(t["ansible.builtin.assert"]["that"])
    for key in REQUIRED_GDPR:
        assert key in that, f"assert does not check gdpr.{key}"


def test_pairing_table_has_no_forbidden_column_and_a_retention_clock():
    table = yaml.safe_load(TABLE.read_text(encoding="utf-8"))
    assert forbidden_columns(table) == []
    assert "revoked_at" in {c["key"] for c in table["schema"]["columns"]}
    broken = {"schema": {"columns": [{"key": "imei"}, {"key": "last_location"}, {"key": "slug"}]}}
    assert forbidden_columns(broken) == ["imei", "last_location"]


def test_retention_claim_matches_the_code():
    ok, why = retention_is_honest(GATEWAY.read_text(encoding="utf-8"), _plugin())
    assert ok, why
    # red: a writer appears and no job is declared
    ok, _ = retention_is_honest('req = urllib.request.Request(u, method="POST")', _plugin())
    assert not ok
    # red: no writer, but the note claims nothing
    ok, _ = retention_is_honest("", {"gdpr": {"notes": "all good"}})
    assert not ok


def test_dsar_maps_and_register_carry_the_service():
    for path in (ERASURE, EXPORT):
        entries = {e["id"]: e for e in yaml.safe_load(path.read_text())["services"]}
        e = entries.get("svc_device-gateway")
        assert e, f"{path.name} lacks svc_device-gateway"
        assert e["flag"] == "install_device_gateway" and e["method"] == "manual"
        assert "device-client" in e["note"]
    assert "svc_device-gateway" in REGISTER.read_text(encoding="utf-8")


def test_policy_doc_matches_the_register_row():
    text = DOC.read_text(encoding="utf-8")
    g = _plugin()["gdpr"]
    assert f"**{g['retention_days']} days**" in text, "doc retention must equal retention_days"
    assert g["legal_basis"] in text
    # Signed 2026-10-02: the page must say WHO confirmed it and WHEN.
    assert "CONFIRMED by the operator" in text, "an unsigned proposal must not read as policy"
    readme = (REPO / "docs/systems/device-gateway/README.md").read_text(encoding="utf-8")
    assert "docs/compliance/devices.md" in readme
