"""multi-rate-vat unit — offline half.

A real Czech invoice mixes VAT rates (2026-INV-101: 21% on 1000 + 12% on
500). Retro-red: today's IsdocImporter._localtext(doc, "TaxableAmount")
walks the WHOLE document and returns the FIRST match, so a two-TaxSubTotal
invoice reports only the first rate's base/vat (1000/210) instead of the sum
(1500/270) — this test fails on that tree. After the fix, parse() sums across
every TaxSubTotal and carries the per-rate breakdown alongside the totals.
"""
import importlib.util
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
FIXTURE = REPO / "state" / "fixtures" / "isdoc-fixture-multirate"
TABLES = REPO / "state" / "keap-tables"
INDEX = {"by_key": {("ICO", "00000112"): "synthetic-mesto-lipno",
                     ("ICO", "00000113"): "synthetic-svoboda-petr"}, "by_name": {}}


def _load():
    import sys
    sys.path.insert(0, str(REPO / "files" / "anatomy" / "module_utils"))
    import nos_digest
    spec = importlib.util.spec_from_file_location("digest_import_isdoc",
                                                  REPO / "tools" / "digest-import-isdoc.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return nos_digest, mod


def _bundle():
    nd, mod = _load()
    imp = mod.IsdocImporter("isdoc-fixture-multirate", INDEX, fixture_mode=True)
    bundle, errors = nd.run_importer(imp, str(FIXTURE), TABLES)
    return nd, imp, bundle, errors


def test_two_rates_sum_into_net_and_vat():
    _nd, _imp, bundle, errors = _bundle()
    assert errors == [], errors
    inv = bundle["deterministic"]["invoice"][0]
    assert inv["net_amount"] == 1500.0
    assert inv["vat_amount"] == 270.0
    assert round(inv["net_amount"] + inv["vat_amount"], 2) == inv["payable_amount"] == 1770.0


def test_per_rate_breakdown_is_carried_and_sums_match_the_totals():
    _nd, _imp, bundle, _errors = _bundle()
    inv = bundle["deterministic"]["invoice"][0]
    breakdown = inv["vat_breakdown"]
    assert len(breakdown) == 2
    rates = {round(r["rate"]): (r["base"], r["vat"]) for r in breakdown}
    assert rates == {21: (1000.0, 210.0), 12: (500.0, 60.0)}
    assert round(sum(r["base"] for r in breakdown), 2) == inv["net_amount"]
    assert round(sum(r["vat"] for r in breakdown), 2) == inv["vat_amount"]


def test_payable_amount_rounds_2dp_same_as_net_and_vat_siblings():
    """LAND-WITH-EDITS fix: payable_amount used to skip round(...,2) while
    net_amount/vat_amount didn't — an inconsistency that can false-mismatch
    the crosscheck's payable compare on a real multi-decimal invoice.
    2026-INV-102 carries 3-decimal PayableAmount/TaxableAmount/TaxAmount."""
    _nd, _imp, bundle, errors = _bundle()
    assert errors == [], errors
    inv = next(i for i in bundle["deterministic"]["invoice"] if i["document_number"] == "2026-INV-102")
    assert inv["payable_amount"] == round(1234.567, 2) == 1234.57
    assert inv["net_amount"] == round(1000.567, 2) == 1000.57
    assert inv["vat_amount"] == round(234.000, 2) == 234.0
    # same round(...,2) path as net/vat — no float drift, no separate rounding rule
    assert round(inv["net_amount"] + inv["vat_amount"], 2) == inv["payable_amount"]
