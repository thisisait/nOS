"""invoice-verify CLI — the approve producer (verify-writeback-needs-writer)
and the party-onboard mint (party-onboarding-from-invoice).

RETRO-RED: before tools/invoice-verify.py existed there was no producer that
set pending-invoice-verify.resolution, and no mint from an unknown IČO.
Importing this module failed; party_from_fields did not exist.
"""
from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
APPLE_ICO = "28897501"  # checksum-ok; the vision-fixture vendor the seed names
ROW = {
    "slug": "piv-foo-extract-json",
    "sidecar_id": "foo.extract.json",
    "fields": {
        "seller.ico": {"value": APPLE_ICO, "confidence": 0.0, "source": "text-model"},
        "seller.name": {"value": "Apple Czech s.r.o.", "confidence": 0.0, "source": "text-model"},
        "buyer.ico": {"value": "25596641", "confidence": 0.0, "source": "text-model"},
        "buyer.name": {"value": "Buyer s.r.o.", "confidence": 0.0, "source": "text-model"},
    },
    "resolution": "pending",
}


def _load():
    spec = importlib.util.spec_from_file_location(
        "invoice_verify", REPO / "tools" / "invoice-verify.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_decision_values_stamps_approved_and_refuses_pending():
    mod = _load()
    out = mod.decision_values(ROW, "approved", "pazny", "2026-09-20")
    assert out["resolution"] == "approved"
    assert out["resolved_by"] == "pazny"
    assert out["resolved_at"] == 1789862400
    assert out["slug"] == ROW["slug"]
    with pytest.raises(ValueError, match="approved|rejected"):
        mod.decision_values(ROW, "pending", "pazny", "2026-09-20")


def test_party_from_fields_mints_deterministic_org_slug():
    mod = _load()
    party, tax = mod.party_from_fields(ROW["fields"], "seller")
    assert party["slug"] == f"party-ico-{APPLE_ICO}"
    assert party["legal_name"] == "Apple Czech s.r.o."
    assert party["party_kind"] == "org"
    assert party["role"] == "counterparty"
    assert tax == {"slug": f"pti-ico-{APPLE_ICO}", "party": party["slug"],
                   "scheme": "ICO", "value": APPLE_ICO}


def test_party_from_fields_accepts_json_string_and_buyer_side():
    mod = _load()
    party, tax = mod.party_from_fields(json.dumps(ROW["fields"]), "buyer")
    assert tax["value"] == "25596641"
    assert party["slug"] == "party-ico-25596641"


def test_party_from_fields_refuses_bad_checksum_and_synthetic():
    mod = _load()
    with pytest.raises(ValueError, match="checksum"):
        mod.party_from_fields({"seller.ico": {"value": "87654321"}}, "seller")
    with pytest.raises(ValueError, match="synthetic"):
        mod.party_from_fields({"seller.ico": {"value": "00000112"}}, "seller")
    with pytest.raises(ValueError, match="digits"):
        mod.party_from_fields({"seller.ico": {"value": "not-an-ico"}}, "seller")


def test_audit_payload_is_table_upsert_hmac_shape():
    mod = _load()
    payload = mod.audit_payload("piv-foo-extract-json", "approved", "pazny")
    assert payload["type"] == "table.upsert"
    assert payload["source"] == "invoice-verify"
    assert payload["actor_id"] == "operator:pazny"
    assert payload["result"]["table"] == "pending-invoice-verify"
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    hdr = mod.hmac_headers("secret", body, ts="1700000000")
    expect = hmac.new(b"secret", b"1700000000." + body, hashlib.sha256).hexdigest()
    assert hdr["X-Wing-Signature"] == expect
    assert hdr["X-Wing-Timestamp"] == "1700000000"


def test_emit_audit_unset_secret_is_best_effort(monkeypatch, capsys):
    mod = _load()
    monkeypatch.delenv("WING_EVENTS_HMAC_SECRET", raising=False)
    monkeypatch.setattr(mod, "hmac_secret", lambda: "")
    assert mod.emit_audit("piv-x", "approved", "pazny") is False
    assert "WING_EVENTS_HMAC_SECRET unset" in capsys.readouterr().err


def test_hmac_secret_reads_secrets_yml_when_env_empty(monkeypatch, tmp_path):
    mod = _load()
    monkeypatch.delenv("WING_EVENTS_HMAC_SECRET", raising=False)
    nos = tmp_path / ".nos"
    nos.mkdir()
    (nos / "secrets.yml").write_text('wing_events_hmac_secret: "from-yml"\n', encoding="utf-8")
    monkeypatch.setattr(mod.pathlib.Path, "home", staticmethod(lambda: tmp_path))
    assert mod.hmac_secret() == "from-yml"


def test_approve_dry_run_does_not_write(monkeypatch, capsys):
    mod = _load()
    monkeypatch.setattr(mod, "_row", lambda slug: dict(ROW))
    written = []
    monkeypatch.setattr(mod, "_write", lambda row: written.append(row))
    monkeypatch.setattr(mod, "emit_audit", lambda *a: True)
    assert mod.main(["approve", "piv-foo-extract-json", "--dry-run"]) == 0
    assert written == []
    dumped = json.loads(capsys.readouterr().out)
    assert dumped["resolution"] == "approved"


def test_onboard_dry_run_prints_party_then_approved(monkeypatch, capsys):
    mod = _load()
    monkeypatch.setattr(mod, "_row", lambda slug: dict(ROW))
    posted = []
    monkeypatch.setattr(mod.digest_absorb, "_post_row", lambda *a: posted.append(a))
    assert mod.main(["onboard", "piv-foo-extract-json", "--dry-run"]) == 0
    assert posted == []
    dumped = json.loads(capsys.readouterr().out)
    assert dumped["then"] == "approved"
    assert dumped["tax"]["value"] == APPLE_ICO
