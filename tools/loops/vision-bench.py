#!/usr/bin/env python3
"""vision-bench runner — files/anatomy/loops/vision-bench.loop.yml.

Runs the invoice VISION pipeline (image -> VLM OCR -> extract -> record) over the
consulting-firm fixture images and scores each extracted field against the ground
truth the image was RENDERED from (state/fixtures/consulting-firm/<slug>.image.txt,
via invoice_fixture.parse_image_txt). Two independent measurements, both decided
by a code oracle — the model never grades itself:

  1. EXTRACTION FIDELITY — does the VLM reproduce what the image shows?
  2. CROSS-CHECK — the extracted (image) payable vs the ISDOC twin's PayableAmount
     (expected.yml.documents) -> agree|mismatch, scored against
     expected.yml.crosscheck. beta-001 is the planted positive control (image
     3600 vs ISDOC 3630 = mismatch).

ONE RUN IS NOT A MEASUREMENT (state/ops-task-families/invoice-extract/family.yml):
--repeat N runs each image N times and pools, reporting per-field accuracy and the
per-doc spread, so a lucky pass cannot read as a ceiling. The report written to
state/vision-bench/last-run.json is the LAST run, never the best.

Exit: 0 ran and pooled accuracy >= --threshold · 3 ran but BELOW floor (a finding,
declared in the loop's findings_exit_codes) · 2 could not run (no images, or the
pipeline failed for every image — e.g. qwen2.5vl:7b not pulled / ollama not armed).

DRY / read-only: writes only the report; absorbs nothing into KEAP.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
from invoice_fixture import parse_image_txt  # noqa: E402

import yaml  # noqa: E402

FIXTURE = REPO / "state" / "fixtures" / "consulting-firm"
PIPELINE = REPO / "tools" / "invoice-vision-pipeline.py"
REPORT_DIR = REPO / "state" / "vision-bench"

# The fields scored for extraction fidelity, each as a (record) -> comparable and
# a (truth) -> comparable. Amounts compared at 2dp; strings exact.
def _num(v):
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def truth_fields(truth: dict) -> dict:
    """The scorable ground truth from a parsed .image.txt."""
    net = round(sum(r["base"] for r in truth.get("rates", [])), 2) if truth.get("rates") else None
    vat = round(sum(r["vat"] for r in truth.get("rates", [])), 2) if truth.get("rates") else None
    return {
        "id": truth.get("id"),
        "issue": truth.get("issue"),
        "due": truth.get("due"),
        "currency": truth.get("currency"),
        "payable": _num(truth.get("payable")),
        "net": net,
        "vat": vat,
        "seller.ico": truth.get("seller_ico"),
        "buyer.ico": truth.get("buyer_ico"),
        "rates": sorted((r["rate"], _num(r["base"]), _num(r["vat"])) for r in truth.get("rates", [])),
    }


def record_fields(record: dict) -> dict:
    """The same shape pulled from the VLM-extracted record dict (isdoc-record)."""
    bd = record.get("vat_breakdown") or []
    return {
        "id": record.get("id"),
        "issue": record.get("issue"),
        "due": record.get("due"),
        "currency": record.get("currency"),
        "payable": _num(record.get("payable")),
        "net": _num(record.get("net")),
        "vat": _num(record.get("vat")),
        "seller.ico": (record.get("seller") or {}).get("ico"),
        "buyer.ico": (record.get("buyer") or {}).get("ico"),
        "rates": sorted((r.get("rate"), _num(r.get("base")), _num(r.get("vat"))) for r in bd),
    }


def score_extraction(record: dict, truth: dict) -> dict:
    """Per-field hit map (code oracle). Returns {field: bool}."""
    t, r = truth_fields(truth), record_fields(record)
    return {k: (t[k] == r[k]) for k in t}


def crosscheck(record: dict, isdoc_payable) -> str:
    """The extracted (image) payable vs the ISDOC twin's PayableAmount."""
    return "agree" if _num(record.get("payable")) == _num(isdoc_payable) else "mismatch"


def _run_pipeline(image: pathlib.Path) -> dict | None:
    """One image through invoice-vision-pipeline.py -> the extracted record dict.
    Returns None if the pipeline fails (model unarmed / no chain)."""
    with tempfile.TemporaryDirectory() as td:
        out = pathlib.Path(td) / "s.extract.json"
        r = subprocess.run([sys.executable, str(PIPELINE), str(image), "--out", str(out)],
                           capture_output=True, text=True)
        if r.returncode != 0 or not out.exists():
            print(f"  pipeline failed on {image.name} (exit {r.returncode}): {r.stderr[-200:]}", file=sys.stderr)
            return None
        raw = out.read_text(encoding="utf-8")
        i = raw.find("{")
        if i < 0:
            print(f"  pipeline sidecar is not JSON on {image.name}", file=sys.stderr)
            return None
        rec = json.JSONDecoder().raw_decode(raw[i:])[0]
        return rec.get("record", {}) if isinstance(rec, dict) else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fixture", default=str(FIXTURE))
    ap.add_argument("--images", default=None, help="dir of <slug>.jpg (default <fixture>/images)")
    ap.add_argument("--repeat", type=int, default=3, help="runs per image (one run is not a measurement)")
    ap.add_argument("--threshold", type=float, default=0.85, help="pooled accuracy floor")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    fx = pathlib.Path(args.fixture)
    images = pathlib.Path(args.images) if args.images else fx / "images"
    expected = yaml.safe_load((fx / "expected.yml").read_text())
    docs, xcheck = expected.get("documents", {}), expected.get("crosscheck", {})

    cases = []
    for txt in sorted(fx.glob("*.image.txt")):
        slug = txt.name.replace(".image.txt", "")
        img = images / f"{slug}.jpg"
        if not img.exists():
            continue
        truth = parse_image_txt(txt.read_text(encoding="utf-8"))
        cases.append((slug, img, truth, truth.get("id")))
    if not cases:
        print(f"REFUSING: no scorable images in {images} (run tools/gen-invoice-images.py first)", file=sys.stderr)
        return 2

    hits = total = 0
    per_field: dict[str, list[int]] = {}
    per_doc_runs: dict[str, list[float]] = {}
    xhits = xtotal = 0
    ran = 0
    for slug, img, truth, docnum in cases:
        for _ in range(args.repeat):
            record = _run_pipeline(img)
            if record is None:
                continue
            ran += 1
            sc = score_extraction(record, truth)
            doc_hits = sum(1 for v in sc.values() if v)
            hits += doc_hits
            total += len(sc)
            per_doc_runs.setdefault(slug, []).append(round(doc_hits / len(sc), 3))
            for k, v in sc.items():
                per_field.setdefault(k, []).append(1 if v else 0)
            if docnum in docs:
                verdict = crosscheck(record, docs[docnum].get("payable"))
                xtotal += 1
                if verdict == xcheck.get(docnum):
                    xhits += 1

    if ran == 0:
        print("REFUSING: the vision pipeline produced no records — is qwen2.5vl:7b pulled and ollama armed?",
              file=sys.stderr)
        return 2

    accuracy = round(hits / total, 4) if total else 0.0
    report = {
        "accuracy": accuracy,
        "runs": ran,
        "repeat": args.repeat,
        "threshold": args.threshold,
        "crosscheck_accuracy": round(xhits / xtotal, 4) if xtotal else None,
        "per_field": {k: round(sum(v) / len(v), 3) for k, v in sorted(per_field.items())},
        "per_doc": {k: {"runs": v, "spread": round(max(v) - min(v), 3)} for k, v in per_doc_runs.items()},
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "last-run.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"vision-bench: accuracy {accuracy:.3f} over {ran} run(s) "
              f"(threshold {args.threshold}); crosscheck {report['crosscheck_accuracy']}")
        for k, v in report["per_field"].items():
            print(f"  {k:<12} {v:.3f}")
        for k, v in report["per_doc"].items():
            print(f"  {k}: runs {v['runs']} spread {v['spread']}")

    return 0 if accuracy >= args.threshold else 3


def _self_check() -> None:
    """Offline: the CODE ORACLE, validated without the model. A faithful record
    scores 1.0; a dropped field scores below; the planted beta mismatch reads
    'mismatch'. Runnable via `python3 vision-bench.py --self-check`."""
    truth = parse_image_txt(
        "Doklad c.: 2026-BETA-001\nDatum vystaveni: 2026-03-01\nDatum splatnosti: 2026-03-15\n"
        "Mena: CZK\nZaklad 21%: 3000  DPH 21%: 630\nCastka k uhrade: 3600\n"
        "Dodavatel ICO: 00000132 (Beta Sluzby s.r.o.)\nOdberatel ICO: 00000136 (Beta Odberatel a.s.)\n")
    faithful = {"id": "2026-BETA-001", "issue": "2026-03-01", "due": "2026-03-15", "currency": "CZK",
                "payable": 3600, "net": 3000, "vat": 630,
                "vat_breakdown": [{"rate": 21, "base": 3000, "vat": 630}],
                "seller": {"ico": "00000132"}, "buyer": {"ico": "00000136"}}
    sc = score_extraction(faithful, truth)
    assert all(sc.values()), [k for k, v in sc.items() if not v]
    dropped = {**faithful, "payable": 9999}
    assert score_extraction(dropped, truth)["payable"] is False
    # cross-check: image payable 3600 vs ISDOC twin 3630 -> mismatch (the control)
    assert crosscheck(faithful, 3630) == "mismatch"
    assert crosscheck(faithful, 3600) == "agree"
    print("vision-bench self-check OK")


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        _self_check()
    else:
        raise SystemExit(main())
