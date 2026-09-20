#!/usr/bin/env python3
"""invoice-vision-pipeline — the runnable seam between the two one_shot
stages: VLM(image) -> OCR text -> extract(text) -> ISDOC record -> sidecar.

Before this file the two agents (invoice-vision-ocr, invoice-extract) existed
but nothing joined them — Stage A's `{"text": "..."}` chain had no caller that
fed it into Stage B's prompt, so "the real run" (image in, ISDOC record out)
was prose describing two disconnected one_shot calls. This wires it: two
`php bin/run-agent.php` invocations, Stage A's output becoming Stage B's
--prompt.

CEILING (flagged, not built): OneShot's transport (LLMResponse) carries no
per-token logprobs, so this pipeline cannot compute a REAL per-field decode
confidence — Ollama's own /api/chat does expose logprobs; wiring that in
behind OneShot is a separate, larger transport change. Every field here is
therefore stamped confidence=0.0, honestly, not faked — which keeps every
pipeline-produced sidecar below CONFIDENCE_FLOOR (isdoc-extract-sidecar
.schema.yaml) on top of build_sidecar()'s own verified:false, so it always
lands in VisionImporter's operator-verify queue and never auto-absorbs.

Does NOT run a real model — shells to bin/run-agent.php, which needs a pulled
qwen2.5vl:7b and a live ollama binding to do anything but fail. Exit 2 if
either stage's chain is empty (schema-invalid / no chain), matching
run-agent.php's own exit code for that case.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
WING = REPO / "files" / "anatomy" / "wing"
RUN_AGENT = WING / "bin" / "run-agent.php"

sys.path.insert(0, str(REPO / "tools"))
import invoice_extract  # noqa: E402


def _run_agent(args: list[str]) -> dict:
    """One `php bin/run-agent.php` call, JSON summary parsed. List args, not
    a shell string — a prompt full of newlines/quotes (Stage A's OCR text)
    must never round-trip through a shell."""
    out = subprocess.run(
        ["php", str(RUN_AGENT), *args], cwd=WING,
        capture_output=True, text=True, timeout=300,
    )
    # exit 0 = idle/satisfied, 1 = a schema-invalid one_shot chain (still a
    # completed run, caller decides what that means); only 2 (config error)
    # and anything else are unparseable failures.
    if out.returncode not in (0, 1):
        raise RuntimeError(f"run-agent {args[0]} failed (exit {out.returncode}): {out.stderr[-500:]}")
    return json.loads(out.stdout)


def run_stage_a(image_path: str) -> str:
    """invoice-vision-ocr one_shot: image in, free OCR text out."""
    summary = _run_agent(["--agent=invoice-vision-ocr", f"--image={image_path}"])
    if summary.get("chain") is None:
        raise RuntimeError(f"stage A (invoice-vision-ocr) produced no chain: {summary.get('chain_error')}")
    return summary["chain"]["text"]


def run_stage_b(ocr_text: str) -> dict:
    """invoice-extract one_shot: OCR text in, ISDOC record dict out."""
    summary = _run_agent(["--agent=invoice-extract", f"--prompt={ocr_text}"])
    if summary.get("chain") is None:
        raise RuntimeError(f"stage B (invoice-extract) produced no chain: {summary.get('chain_error')}")
    return summary["chain"]


def flatten_record(record: dict, prefix: str = "") -> dict:
    """Dotted-key leaves, per isdoc-extract-sidecar.schema.yaml's `fields`
    convention ("one entry per non-null key in record, dotted for nested").
    Lists (vat_breakdown) are kept whole under their own key — indexing them
    dot-per-item is not asked for by the schema's own examples."""
    out = {}
    for k, v in record.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(flatten_record(v, key))
        elif v is not None:
            out[key] = v
    return out


def build_pipeline_sidecar(record: dict) -> dict:
    """Assemble the .extract.json sidecar VisionImporter.parse() reads, from
    a raw two-stage pipeline record. Validates against the frozen ISDOC
    record schema first — a schema-violating record must never reach a
    sidecar file at all."""
    errors = invoice_extract.validate_record(record)
    if errors:
        raise ValueError(f"stage B emitted a schema-violating record: {errors}")
    fields = {
        k: {"value": v, "confidence": 0.0, "source": "text-model"}
        for k, v in flatten_record(record).items()
    }
    return invoice_extract.build_sidecar(record, fields)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("image", help="path to the invoice scan/PDF page")
    ap.add_argument("--out", required=True, help="path to write the .extract.json sidecar")
    args = ap.parse_args()

    ocr_text = run_stage_a(args.image)
    record = run_stage_b(ocr_text)
    sidecar = build_pipeline_sidecar(record)

    out = pathlib.Path(args.out)
    out.write_text(json.dumps(sidecar, indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        f"wrote {out} — {len(sidecar['fields'])} field(s), verified=false "
        "(operator-verify queue; see module docstring's confidence ceiling)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
