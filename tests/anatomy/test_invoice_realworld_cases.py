"""invoice-realworld-cases — rounding, credit note, reverse charge, offline.

RETRO-RED: before this commit parse() dropped PayableRoundingAmount and
DocumentType, reconcile refused every net+vat!=payable, and derive_entry
posted gross not payable. Each assertion below fails on that tree.
"""
from __future__ import annotations

import importlib.util
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
FIXTURE = REPO / "state" / "fixtures" / "isdoc-realworld"
TABLES = REPO / "state" / "keap-tables"
INDEX = {"by_key": {("ICO", "00000112"): "synthetic-mesto-lipno",
                     ("ICO", "00000113"): "synthetic-svoboda-petr"}, "by_name": {}}


def _load():
    import sys
    sys.path.insert(0, str(REPO / "files" / "anatomy" / "module_utils"))
    import nos_digest
    spec = importlib.util.spec_from_file_location(
        "digest_import_isdoc", REPO / "tools" / "digest-import-isdoc.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return nos_digest, mod


def _invoices():
    nd, mod = _load()
    imp = mod.IsdocImporter("isdoc-realworld", INDEX, fixture_mode=True)
    bundle, errors = nd.run_importer(imp, str(FIXTURE), TABLES)
    assert errors == [], errors
    return {i["document_number"]: i for i in bundle["deterministic"]["invoice"]}


def test_rounding_line_is_parsed_and_reconciles():
    inv = _invoices()["2026-INV-ROUND"]
    assert inv["rounding_amount"] == 1.0
    assert inv["payable_amount"] == 1211.0
    import sys
    sys.path.insert(0, str(REPO / "files" / "anatomy" / "module_utils"))
    import nos_accounting
    assert nos_accounting.reconcile_invoice(inv) == []


def test_credit_note_is_kind_not_a_batch_poison():
    inv = _invoices()["2026-INV-CN"]
    assert inv["document_kind"] == "credit_note"
    import sys
    sys.path.insert(0, str(REPO / "files" / "anatomy" / "module_utils"))
    import nos_accounting
    assert nos_accounting.reconcile_invoice(inv) == []


def test_reverse_charge_is_flagged():
    inv = _invoices()["2026-INV-PDP"]
    assert inv["vat_regime"] == "reverse_charge"
    assert inv["vat_amount"] == 0.0
    assert inv["payable_amount"] == 1000.0
