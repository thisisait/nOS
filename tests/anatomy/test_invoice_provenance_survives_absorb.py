"""provenance-keep unit (2026-09-20) — confidence + source survive onto the
absorbed invoice row.

Before this unit: VisionImporter.parse() copied `record` into the bundle row
and dropped `fields`/`verified` entirely; digest_absorb.absorb strips `_prov`.
Neither confidence nor source survived past absorb — an absorbed row looked
identical whether it came from deterministic ISDOC or a 0.86-confidence
vision extract. RETRO-RED: reverting either compose() stamp (source_kind, the
overall_confidence copy) makes this file fail again.
"""
import importlib.util
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
VISION_FIXTURE = REPO / "state" / "fixtures" / "vision-fixture"
ISDOC_FIXTURE = REPO / "state" / "fixtures" / "isdoc-fixture"
TABLES = REPO / "state" / "keap-tables"
VISION_INDEX = {"by_key": {("ICO", "00000112"): "synthetic-mesto-lipno",
                           ("ICO", "00000113"): "synthetic-svoboda-petr"}, "by_name": {}}


def _load(name, filename):
    import sys
    sys.path.insert(0, str(REPO / "files" / "anatomy" / "module_utils"))
    import nos_digest
    spec = importlib.util.spec_from_file_location(name, REPO / "tools" / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return nos_digest, mod


def test_absorbed_vision_row_shows_source_and_confidence():
    nd, mod = _load("digest_import_vision", "digest-import-vision.py")
    imp = mod.VisionImporter("vision-fixture", VISION_INDEX, fixture_mode=True)
    bundle, errors = nd.run_importer(imp, str(VISION_FIXTURE), TABLES)
    assert errors == [], errors
    inv = bundle["deterministic"]["invoice"][0]
    assert inv["source"] == "vision"
    assert inv["verified"] is True
    assert inv["overall_confidence"] is not None
    # the fixture's lowest per-field confidence for 2026-INV-201 is 0.95
    assert 0.94 < inv["overall_confidence"] < 0.96


def test_absorbed_isdoc_row_is_always_verified_with_no_confidence_to_report():
    import yaml
    nd, mod = _load("digest_import_isdoc", "digest-import-isdoc.py")
    fixture_index = yaml.safe_load(
        (REPO / "state" / "fixtures" / "isdoc-fixture" / "expected.yml").read_text()
    ) if (ISDOC_FIXTURE / "expected.yml").exists() else None
    imp = mod.IsdocImporter("isdoc-fixture", VISION_INDEX, fixture_mode=True)
    bundle, errors = nd.run_importer(imp, str(ISDOC_FIXTURE), TABLES)
    invoices = bundle["deterministic"].get("invoice", [])
    assert invoices, "isdoc fixture produced no rows — cannot assert on source stamping"
    for inv in invoices:
        assert inv["source"] == "isdoc"
        assert inv["verified"] is True
        assert "overall_confidence" not in inv  # nothing to have been unconfident about
    del fixture_index  # unused; kept for future expected.yml cross-check


def test_confidence_survives_a_full_absorb_strip_provenance_pass():
    """_prov is stripped at absorb (importer provenance) — source/verified/
    overall_confidence are ROW COLUMNS, not _prov, so strip_provenance() must
    leave them untouched. This is the exact bug shape: something that looks
    like metadata gets discarded alongside real metadata."""
    nd, mod = _load("digest_import_vision", "digest-import-vision.py")
    imp = mod.VisionImporter("vision-fixture", VISION_INDEX, fixture_mode=True)
    bundle, errors = nd.run_importer(imp, str(VISION_FIXTURE), TABLES)
    assert errors == []
    stripped = nd.strip_provenance(bundle["deterministic"])
    inv = stripped["invoice"][0]
    assert inv["source"] == "vision"
    assert inv["overall_confidence"] is not None
    assert "_prov" not in inv
