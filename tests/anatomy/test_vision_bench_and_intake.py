"""vision-bench + invoice-vision-intake — pin the code oracles in CI.

The runnable self-checks in these scripts live under `if __name__ == "__main__"`,
which pytest never executes (it exec_module's them). These tests are the CI-run
copy: the scoring oracle (vision-bench), the held gate + queue-row shape
(intake), and the ONE shared .image.txt parser both the generator and the
benchmark bind to.
"""
import importlib.util
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]


def _load(name, relpath):
    spec = importlib.util.spec_from_file_location(name, REPO / relpath)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


VB = _load("vision_bench", "tools/loops/vision-bench.py")
IV = _load("invoice_vision_intake", "tools/invoice-vision-intake.py")
FX = _load("invoice_fixture", "tools/invoice_fixture.py")

_BETA = ("Doklad c.: 2026-BETA-001\nDatum vystaveni: 2026-03-01\nDatum splatnosti: 2026-03-15\n"
         "Mena: CZK\nZaklad 21%: 3000  DPH 21%: 630\nCastka k uhrade: 3600\n"
         "Dodavatel ICO: 00000132 (Beta Sluzby s.r.o.)\nOdberatel ICO: 00000136 (Beta Odberatel a.s.)\n")
_FAITHFUL = {"id": "2026-BETA-001", "issue": "2026-03-01", "due": "2026-03-15", "currency": "CZK",
             "payable": 3600, "net": 3000, "vat": 630,
             "vat_breakdown": [{"rate": 21, "base": 3000, "vat": 630}],
             "seller": {"ico": "00000132"}, "buyer": {"ico": "00000136"}}


def test_parser_reads_displayed_values_including_a_planted_discrepancy():
    t = FX.parse_image_txt(_BETA)
    assert t["id"] == "2026-BETA-001" and t["payable"] == 3600.0   # the IMAGE value, not the ISDOC 3630
    assert t["seller_ico"] == "00000132" and t["buyer_ico"] == "00000136"
    assert t["rates"] == [{"rate": 21, "base": 3000.0, "vat": 630.0}]


def test_score_extraction_is_exact_and_catches_a_drop():
    truth = FX.parse_image_txt(_BETA)
    sc = VB.score_extraction(_FAITHFUL, truth)
    assert all(sc.values()), [k for k, v in sc.items() if not v]
    assert VB.score_extraction({**_FAITHFUL, "payable": 9999}, truth)["payable"] is False
    assert VB.score_extraction({**_FAITHFUL, "seller": {"ico": "99999999"}}, truth)["seller.ico"] is False


def test_crosscheck_flags_the_planted_beta_mismatch():
    # image payable 3600 vs the ISDOC twin's 3630 -> mismatch (the positive control)
    assert VB.crosscheck(_FAITHFUL, 3630) == "mismatch"
    assert VB.crosscheck(_FAITHFUL, 3600) == "agree"


def test_intake_held_gate_matches_the_importer_contract():
    below = {"verified": True, "fields": {"payable": {"value": 1, "confidence": 0.0, "source": "text-model"}}}
    unverified = {"verified": False, "fields": {"payable": {"value": 1, "confidence": 0.99, "source": "vlm"}}}
    clean = {"verified": True, "fields": {"payable": {"value": 1, "confidence": 0.99, "source": "vlm"}}}
    assert IV.is_held(below) is True          # below CONFIDENCE_FLOOR
    assert IV.is_held(unverified) is True     # not verified
    assert IV.is_held(clean) is False         # verified + above floor
    assert IV.is_held({"verified": True, "fields": {"x": "not-a-dict"}}) is True  # malformed -> held, not crash
    assert IV.CONFIDENCE_FLOOR == 0.85        # read from the schema, not a literal here


def test_intake_verify_row_shape():
    row = IV.verify_row("2026-BETA-001.extract.json", {"verified": False, "fields": {"x": {"confidence": 0.0}}})
    assert row["sidecar_id"] == "2026-BETA-001.extract.json"   # the stable join key parse() looks up by
    assert row["slug"] == "piv-2026-beta-001-extract-json"
    assert row["resolution"] == "pending"
    assert row["fields"] == {"x": {"confidence": 0.0}}


def test_pulse_absorb_does_not_enable_fixture_mode():
    """Nightly absorb must not book 000001xx IČOs into the live books."""
    import yaml
    plugin = yaml.safe_load(
        (REPO / "files/anatomy/plugins/invoice-vision-base/plugin.yml").read_text())
    jobs = {j["name"]: j for j in plugin["pulse"]["jobs"]}
    args = jobs["absorb-approved"].get("args") or []
    assert "--absorb" in args
    assert "--fixture-mode" not in args
