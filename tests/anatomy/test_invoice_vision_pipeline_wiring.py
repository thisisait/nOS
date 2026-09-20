"""invoice-vision-pipeline — the seam that JOINS invoice-vision-ocr's OCR
text output to invoice-extract's prompt input, offline half.

Before tools/invoice-vision-pipeline.py existed the two one_shot agents were
disconnected: nothing shelled Stage A, took its {"text": ...} chain, and fed
it as Stage B's --prompt. This gate pins the pure logic (flatten_record,
build_pipeline_sidecar) and, via a monkeypatched subprocess, the two-stage
wiring itself — without running a real model.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location(
        "invoice_vision_pipeline", REPO / "tools" / "invoice-vision-pipeline.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


RECORD = {
    "id": "2026-INV-401", "currency": "CZK", "payable": 1210.0,
    "net": 1000.0, "vat": 210.0,
    "vat_breakdown": [{"rate": 21.0, "base": 1000.0, "vat": 210.0}],
    "seller": {"ico": "00000112", "name": "Mesto Lipno (synthetic)"},
    "buyer": {"ico": "00000113", "name": "Petr Svoboda (synthetic)"},
}


def test_flatten_record_dots_nested_keys_and_drops_nulls():
    mod = _load()
    flat = mod.flatten_record(RECORD)
    assert flat["id"] == "2026-INV-401"
    assert flat["seller.ico"] == "00000112"
    assert flat["buyer.name"] == "Petr Svoboda (synthetic)"
    # a list value is kept whole under its own key, not indexed per item
    assert flat["vat_breakdown"] == RECORD["vat_breakdown"]
    assert dict(RECORD, extra=None)  # sanity: None is filterable
    flat_with_null = mod.flatten_record(dict(RECORD, extra=None))
    assert "extra" not in flat_with_null


def test_build_pipeline_sidecar_stamps_every_field_below_the_confidence_floor():
    mod = _load()
    sidecar = mod.build_pipeline_sidecar(RECORD)
    assert sidecar["record"] == RECORD
    assert sidecar["verified"] is False
    assert sidecar["fields"], "no fields were produced"
    for key, field in sidecar["fields"].items():
        assert field["confidence"] == 0.0, (
            f"{key} claimed a non-zero decode confidence — this transport has "
            "no logprobs to back that claim (see module docstring's ceiling)"
        )
        assert field["source"] == "text-model"
        assert 0.0 < 0.85, "sanity: 0.0 sits below CONFIDENCE_FLOOR"
    # every field this sidecar carries must independently satisfy the sidecar
    # schema's own per-field contract — reuse the frozen validator, don't
    # hand-roll a second check that could drift from it.
    import sys
    sys.path.insert(0, str(REPO / "tools"))
    import invoice_extract
    assert invoice_extract.validate_record(sidecar["record"]) == []


def test_build_pipeline_sidecar_refuses_a_schema_violating_record():
    mod = _load()
    bad = dict(RECORD, currency="USD")  # not in the ISDOC enum
    with pytest.raises(ValueError, match="schema-violating"):
        mod.build_pipeline_sidecar(bad)


class _FakeCompleted:
    def __init__(self, returncode, stdout):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = ""


def test_stage_a_reads_the_text_field_out_of_run_agents_chain(monkeypatch):
    mod = _load()
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        return _FakeCompleted(0, json.dumps({"chain": {"text": "INVOICE 2026-INV-401 ..."}}))

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    text = mod.run_stage_a("/tmp/page.png")
    assert text == "INVOICE 2026-INV-401 ..."
    assert "--agent=invoice-vision-ocr" in seen["cmd"]
    assert "--image=/tmp/page.png" in seen["cmd"]


def test_stage_b_feeds_stage_as_text_as_its_prompt(monkeypatch):
    mod = _load()
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        return _FakeCompleted(0, json.dumps({"chain": RECORD}))

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    record = mod.run_stage_b("INVOICE 2026-INV-401 ...")
    assert record == RECORD
    assert "--agent=invoice-extract" in seen["cmd"]
    assert "--prompt=INVOICE 2026-INV-401 ..." in seen["cmd"]


def test_a_stage_with_no_chain_refuses_rather_than_forging_a_sidecar(monkeypatch):
    mod = _load()

    def fake_run(cmd, **kw):
        return _FakeCompleted(1, json.dumps({"chain": None, "chain_error": "not JSON"}))

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="no chain"):
        mod.run_stage_a("/tmp/page.png")
    with pytest.raises(RuntimeError, match="no chain"):
        mod.run_stage_b("some text")
