"""D5 unit 2 (verify-write-back) — retro-red gate.

RETRO-RED (verified manually while authoring this test, same idiom as
tests/anatomy/test_gdpr_controller_records_runtime_only.py's docstring):
before this commit `VisionImporter.__init__` took no `pending_verify` kwarg
and `parse()` had no `_pending_resolution` read at all — an
`approved`-resolution row could not change parse() output because nothing
looked it up. `TypeError: __init__() got an unexpected keyword argument
'pending_verify'` is what every test below raised on the pre-D5 tree.

Own fixture (state/fixtures/verify-write-back) rather than the shared
vision-fixture: D1's own sidecars there omit issue/due/net/vat (fine while
they always stayed held — `compose()` never reached them), and this test's
whole point is proving an approved one DOES reach compose(), which needs a
complete record. The carried-forward D2-judge note stands regardless: these
are real *.extract.json (unlike D1's .image.txt stand-ins), so this exercises
the real read without needing a live KEAP.
"""
from __future__ import annotations

import importlib.util
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
FIXTURE = REPO / "state" / "fixtures" / "verify-write-back"
TABLES = REPO / "state" / "keap-tables"
INDEX = {"by_key": {("ICO", "00000112"): "synthetic-mesto-lipno",
                     ("ICO", "00000113"): "synthetic-svoboda-petr"}, "by_name": {}}

LOW_CONF_SIDECAR = "held-low-conf.extract.json"
UNVERIFIED_SIDECAR = "held-unverified.extract.json"


def _load():
    import sys
    sys.path.insert(0, str(REPO / "files" / "anatomy" / "module_utils"))
    import nos_digest
    spec = importlib.util.spec_from_file_location("digest_import_vision",
                                                  REPO / "tools" / "digest-import-vision.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return nos_digest, mod


def _bundle(pending_verify):
    nd, mod = _load()
    imp = mod.VisionImporter("vision-fixture", INDEX, fixture_mode=True, pending_verify=pending_verify)
    bundle, errors = nd.run_importer(imp, str(FIXTURE), TABLES)
    return imp, bundle, errors


def test_no_pending_row_stays_held_exactly_as_today():
    imp, bundle, errors = _bundle({})
    assert errors == []
    assert "2026-INV-301" not in {i["document_number"] for i in bundle["deterministic"]["invoice"]}


def test_pending_resolution_stays_held():
    imp, bundle, _errors = _bundle({LOW_CONF_SIDECAR: "pending"})
    assert "2026-INV-301" not in {i["document_number"] for i in bundle["deterministic"]["invoice"]}


def test_approved_low_confidence_sidecar_lands_on_reimport():
    imp, bundle, errors = _bundle({LOW_CONF_SIDECAR: "approved"})
    assert errors == []
    doc_numbers = {i["document_number"] for i in bundle["deterministic"]["invoice"]}
    assert "2026-INV-301" in doc_numbers, "approved -> treated verified regardless of raw confidence"


def test_rejected_is_a_durable_tombstone_across_two_import_runs():
    pending = {UNVERIFIED_SIDECAR: "rejected"}
    for run in (1, 2):
        imp, bundle, _errors = _bundle(pending)
        doc_numbers = {i["document_number"] for i in bundle["deterministic"]["invoice"]}
        assert "2026-INV-302" not in doc_numbers, f"run {run}: rejected sidecar resurfaced"
        assert any("tombstone" in s for s in imp.skipped), f"run {run}: no tombstone reason recorded"


def test_money_path_unchanged_two_dp_on_the_approved_row():
    _imp, bundle, _errors = _bundle({LOW_CONF_SIDECAR: "approved"})
    inv = next(i for i in bundle["deterministic"]["invoice"] if i["document_number"] == "2026-INV-301")
    assert inv["payable_amount"] == 4840.0, "the fixture sidecar's own payable, unmangled by the write-back read"
