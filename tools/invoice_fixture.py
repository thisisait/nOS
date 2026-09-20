"""invoice_fixture — the ONE reader of the consulting-firm fixture's plain-text
invoice stand-ins (state/fixtures/consulting-firm/<slug>.image.txt).

Shared by the image GENERATOR (tools/gen-invoice-images.py — renders the JPEG
from these fields) and the vision BENCHMARK (tools/loops/vision-bench.py — scores
what the VLM extracts against these same fields). One parser, so "what the image
shows" and "what the benchmark expects" can never drift apart.

The .image.txt is what the IMAGE DISPLAYS — including a planted OCR discrepancy
(beta-001 shows 3600 while its ISDOC twin says 3630), so it is the correct oracle
for image-extraction fidelity; the ISDOC PayableAmount is a separate cross-check.
"""
from __future__ import annotations

import re


def parse_image_txt(text: str) -> dict:
    """label: value stand-in -> {id, issue, due, currency, payable, rates:[{rate,
    base, vat}], seller_ico, seller_name, buyer_ico, buyer_name}. Keeps whatever
    the file DISPLAYS (a planted discrepancy survives)."""
    rec: dict = {"rates": []}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("FAKTURA"):
            continue
        m = re.match(r"Doklad c\.:\s*(.+)", line)
        if m:
            rec["id"] = m.group(1).strip()
        m = re.match(r"Datum vystaveni:\s*(.+)", line)
        if m:
            rec["issue"] = m.group(1).strip()
        m = re.match(r"Datum splatnosti:\s*(.+)", line)
        if m:
            rec["due"] = m.group(1).strip()
        m = re.match(r"Mena:\s*(.+)", line)
        if m:
            rec["currency"] = m.group(1).strip()
        m = re.match(r"Zaklad\s*(\d+)%:\s*([\d.]+)\s+DPH\s*\d+%:\s*([\d.]+)", line)
        if m:
            rec["rates"].append({"rate": int(m.group(1)), "base": float(m.group(2)), "vat": float(m.group(3))})
        m = re.match(r"Castka k uhrade:\s*([\d.]+)", line)
        if m:
            rec["payable"] = float(m.group(1))
        m = re.match(r"Dodavatel ICO:\s*(\d+)\s*\((.+)\)", line)
        if m:
            rec["seller_ico"], rec["seller_name"] = m.group(1), m.group(2).strip()
        m = re.match(r"Odberatel ICO:\s*(\d+)\s*\((.+)\)", line)
        if m:
            rec["buyer_ico"], rec["buyer_name"] = m.group(1), m.group(2).strip()
    return rec
