#!/usr/bin/env python3
"""ČNB daily FX list → KEAP DataTable row payloads.

The n8n PULL template (files/anatomy/n8n/templates/nos-pull-cnb-fx.json) does
the same hops in the editor; THIS file is the oracle the gate scores. Public
data only (no invoices). Stdlib.

  tools/cnb-dtt.py --cnb-file tests/fixtures/cnb-denni_kurz.txt \\
      --schema-file files/anatomy/n8n/templates/cnb-fx.schema.json

  tools/cnb-dtt.py --push --table cnb-fx   # live KEAP; needs KEAP_AGENT_TOKEN_RW
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CNB_URL = (
    "https://www.cnb.cz/cs/financni-trhy/devizovy-trh/"
    "kurzy-devizoveho-trhu/kurzy-devizoveho-trhu/denni_kurz.txt"
)
DEFAULT_SCHEMA = REPO / "files/anatomy/n8n/templates/cnb-fx.schema.json"


def parse_cnb(text: str) -> list[dict]:
    """Parse denni_kurz.txt. First line is `DD.MM.YYYY #seq`; then header; then rows."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise ValueError("empty ČNB list")
    date = _iso_date(lines[0].split()[0])
    header_idx = next(i for i, ln in enumerate(lines) if ln.startswith("země|") or ln.startswith("zeme|"))
    rows = []
    for ln in lines[header_idx + 1 :]:
        parts = ln.split("|")
        if len(parts) < 5:
            raise ValueError(f"bad ČNB row: {ln!r}")
        amount = int(parts[2])
        code = parts[3].strip().upper()
        rate = _czech_float(parts[4]) / amount
        rows.append({
            "slug": f"{date}-{code}",
            "date": date,
            "currency": code,
            "amount": 1,
            "rate": round(rate, 6),
            "country": parts[0],
            "unit": parts[1],
        })
    return rows


def project(rows: list[dict], schema: dict) -> list[dict]:
    """Keep only schema columns. Refuse a required column the parser did not emit."""
    cols = schema["columns"]
    keys = [c["key"] for c in cols]
    required = {c["key"] for c in cols if c.get("required")}
    out = []
    for raw in rows:
        missing = sorted(required - raw.keys())
        if missing:
            raise ValueError(f"row {raw.get('slug')!r} missing required {missing}")
        out.append({k: raw[k] for k in keys if k in raw})
    return out


def schema_from_table_doc(doc: dict) -> dict:
    """Accept either our file shape or GET /agent/v1/tables/:slug (data.schema.columns)."""
    if "columns" in doc:
        return {"slug": doc.get("slug", ""), "columns": doc["columns"]}
    data = doc.get("data") or doc.get("table") or doc
    schema = data.get("schema") or {}
    cols = schema.get("columns") or []
    return {
        "slug": data.get("slug") or doc.get("slug") or "",
        "columns": [{"key": c["key"], "required": bool(c.get("required"))} for c in cols],
    }


def _iso_date(dmy: str) -> str:
    d, m, y = dmy.split(".")
    return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"


def _czech_float(s: str) -> float:
    return float(s.strip().replace(" ", "").replace(",", "."))


def _load_schema(path: Path) -> dict:
    return schema_from_table_doc(json.loads(path.read_text(encoding="utf-8")))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cnb-file", type=Path, help="local denni_kurz.txt (CI). Omit to fetch CNB_URL.")
    p.add_argument("--schema-file", type=Path, default=DEFAULT_SCHEMA)
    p.add_argument("--table", default="cnb-fx")
    p.add_argument("--push", action="store_true", help="upsert into live KEAP (not for CI)")
    args = p.parse_args(argv)

    text = args.cnb_file.read_text(encoding="utf-8") if args.cnb_file else urllib.request.urlopen(CNB_URL, timeout=30).read().decode("utf-8")
    schema = _load_schema(args.schema_file)
    rows = project(parse_cnb(text), schema)
    if not args.push:
        json.dump(rows, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0

    # Live door — imported only when pushing so CI never needs keap_api's docker probe.
    sys.path.insert(0, str(REPO / "tools"))
    from keap_api import write_row  # type: ignore

    for row in rows:
        write_row(args.table, row)
        print(row["slug"], file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
