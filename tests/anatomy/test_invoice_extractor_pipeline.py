"""invoice-structured-extractor unit — offline half.

Two things this gate pins:
(1) constrained decoding is impossible to violate: tools/invoice_extract.py's
    validate_record() rejects a record the ISDOC schema forbids, and a
    low-confidence field never auto-verifies (build_sidecar always emits
    verified:false at extraction time — the operator-verify rung is a later,
    deliberate act, not a model self-grade).
(2) EVERY agent in this pipeline (invoice-vision-ocr, invoice-extract)
    declares backend: ollama + transfers_outside_eu: false — an undeclared
    VLM stage would be the actual cloud-egress path for the highest-value
    target (invoice images).

Retro-red: tools/invoice_extract.py does not exist on today's tree (import
fails); the two agent.yml directories do not exist either.
"""
import pathlib

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
AGENTS_DIR = REPO / "files" / "anatomy" / "agents"


def _load():
    import importlib.util
    import sys
    spec = importlib.util.spec_from_file_location(
        "invoice_extract", REPO / "tools" / "invoice_extract.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


GOOD_RECORD = {
    "id": "2026-INV-401", "currency": "CZK", "payable": 1210.0,
    "net": 1000.0, "vat": 210.0,
    "vat_breakdown": [{"rate": 21.0, "base": 1000.0, "vat": 210.0}],
    "seller": {"ico": "00000112", "name": "Mesto Lipno (synthetic)"},
    "buyer": {"ico": "00000113", "name": "Petr Svoboda (synthetic)"},
}


def test_a_schema_conforming_record_validates_clean():
    mod = _load()
    assert mod.validate_record(GOOD_RECORD) == []


def test_a_schema_violating_record_is_rejected():
    mod = _load()
    bad_currency = dict(GOOD_RECORD, currency="USD")   # not in the enum
    assert mod.validate_record(bad_currency) != []
    extra_field = dict(GOOD_RECORD, business_name="not a real ISDOC field")
    assert mod.validate_record(extra_field) != []
    bad_breakdown = dict(GOOD_RECORD, vat_breakdown=[{"rate": 21.0}])   # missing base/vat
    assert mod.validate_record(bad_breakdown) != []


def test_low_confidence_field_never_auto_verifies():
    mod = _load()
    fields = {
        "id": {"value": "2026-INV-401", "confidence": 0.98, "source": "text-model"},
        "payable": {"value": 1210.0, "confidence": 0.40, "source": "text-model"},
    }
    sidecar = mod.build_sidecar(GOOD_RECORD, fields)
    assert sidecar["verified"] is False


def test_high_confidence_still_never_auto_verifies_at_extraction_time():
    """The operator-verify rung is a deliberate later act, not a model
    self-grade — build_sidecar NEVER sets verified:true, even when every
    field clears the confidence floor."""
    mod = _load()
    fields = {"id": {"value": "2026-INV-401", "confidence": 0.99, "source": "text-model"},
              "payable": {"value": 1210.0, "confidence": 0.97, "source": "text-model"}}
    sidecar = mod.build_sidecar(GOOD_RECORD, fields)
    assert sidecar["verified"] is False
    assert sidecar["record"] == GOOD_RECORD
    assert sidecar["fields"] == fields


@pytest.mark.parametrize("agent_dir", ["invoice-vision-ocr", "invoice-extract"])
def test_every_agent_in_the_pipeline_declares_backend_ollama_and_no_egress(agent_dir):
    y = yaml.safe_load((AGENTS_DIR / agent_dir / "agent.yml").read_text(encoding="utf-8"))
    assert y["model"]["backend"] == "ollama", agent_dir
    assert y["gdpr"]["transfers_outside_eu"] is False, agent_dir
    assert y["gdpr"]["eu_residency"] is True, agent_dir
    assert y["mode"] == "one_shot" and "one_shot" in y, agent_dir


def test_stage_b_schema_reuses_the_frozen_isdoc_record_contract_verbatim():
    frozen = yaml.safe_load((REPO / "state" / "schema" / "isdoc-record.schema.yaml")
                            .read_text(encoding="utf-8"))
    import json
    stage_b = json.loads((AGENTS_DIR / "invoice-extract" / "one-shot.schema.json")
                         .read_text(encoding="utf-8"))
    assert set(stage_b["properties"]) == set(frozen["properties"])
    assert stage_b["required"] == frozen["required"] == []


def test_lift_ico_from_mashed_party_name():
    """A VLM that jammed IČO into seller.name still books via ICO lookup."""
    import sys
    sys.path.insert(0, str(REPO / "tools"))
    import invoice_extract
    rec = invoice_extract.lift_ico_on_record({
        "seller": {"name": "Alfa Rizeni s.r.o.\nIČO 00000131"},
        "buyer": {"name": "Pazny s.r.o. ICO 00000134"},
    })
    assert rec["seller"]["ico"] == "00000131"
    assert rec["buyer"]["ico"] == "00000134"
    assert "IČO" not in rec["seller"]["name"]
    assert "ICO" not in rec["buyer"]["name"]
