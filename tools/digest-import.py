#!/usr/bin/env python3
"""digest-import — the importer-spine round-trip on real input.

The smallest end-to-end proof of the digest pipeline: a CSV of counterparties →
parse → normalize (IČO canonicalisation + deterministic party slug) → compose →
GATE (nos_digest.run_importer → check_bundle) → absorb (upsert by slug). It is
also the first reference importer (CSV, grant milestone M3a) — small enough to
read in one sitting, because everything shared lives in the harness.

  tools/digest-import.py state/fixtures/kolben-import.csv              # gate + print bundle (no writes)
  tools/digest-import.py state/fixtures/kolben-import.csv --absorb     # upsert into KEAP

DEFAULT IS DRY (destructive-op doctrine): it gates and prints the bundle, touches
nothing live. --absorb upserts (skipping slugs already present, so a re-run is a
no-op — the deterministic party-ico-<8> slug PATCHes instead of forking). Tear it
back down with tools/digest-teardown.py on the same bundle.

Exit 0 done/dry · 1 the bundle failed the gate (unsafe) · 2 KEAP unreadable.

CSV columns:  legal_name,ico[,trading_name][,country]   (country defaults CZ)
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import pathlib
import subprocess
import sys
import urllib.error
import urllib.request

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "files" / "anatomy" / "module_utils"))
from keap_api import proxy_header  # noqa: E402
import nos_digest  # noqa: E402

TABLES_DIR = REPO / "state" / "keap-tables"
AGENT = "http://127.0.0.1:8091/agent/v1/tables"


class CsvPartyImporter:
    """CSV counterparties → the EN-16931 party spine (party + party-tax-identity).
    Format knowledge only; the harness owns provenance + the gate."""

    name = "csv-party"
    version = "0.1.0"

    def __init__(self, source_id: str):
        self.source_id = source_id
        self.skipped: list[str] = []

    def parse(self, raw: str) -> list[dict]:
        return list(csv.DictReader(io.StringIO(raw)))

    def normalize(self, records: list[dict]) -> list[dict]:
        out = []
        for r in records:
            norm = nos_digest.normalize_ico(r.get("ico"))
            if norm is None:
                # No usable key → not a deterministic party; the review rung
                # (repos-importer) will handle keyless rows. Skip + report here.
                self.skipped.append(f"{r.get('legal_name', '?')!r}: no valid IČO ({r.get('ico')!r})")
                continue
            out.append({
                "ico8": norm["value"],
                "legal_name": (r.get("legal_name") or "").strip(),
                "trading_name": (r.get("trading_name") or "").strip(),
                "country": (r.get("country") or "CZ").strip(),
            })
        return out

    def compose(self, records: list[dict]) -> dict:
        parties: dict[str, dict] = {}   # dedup by deterministic slug
        taxes: list[dict] = []
        for r in records:
            slug = nos_digest.org_slug(r["ico8"])
            if slug not in parties:      # same IČO twice in one file → ONE party
                row = {"slug": slug, "legal_name": r["legal_name"], "party_kind": "org",
                       "country": r["country"], "notes": f"imported from {self.source_id}"}
                if r["trading_name"]:
                    row["trading_name"] = r["trading_name"]
                parties[slug] = row
                taxes.append({"slug": f"tax-{slug}-ico", "party": slug,
                              "scheme": "ICO", "value": r["ico8"]})
        # KEY ORDER = dependency order: party before the tax rows that rowRef it.
        return {"party": list(parties.values()), "party-tax-identity": taxes}


def _rw_token() -> str:
    tok = os.environ.get("KEAP_AGENT_TOKEN_RW", "").strip()
    if tok:
        return tok
    return subprocess.run(["docker", "exec", "iiab-keap-1", "printenv", "KEAP_AGENT_TOKEN_RW"],
                          capture_output=True, text=True).stdout.strip()


def _existing_slugs(table: str, hdr: dict) -> set:
    req = urllib.request.Request(f"{AGENT}/{table}/rows", headers=hdr)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read() or b"{}")
        # rows nest under `data` ({success, data:{rows:[...]}}) — same envelope
        # the referrers endpoint uses. Reading top-level `rows` here returns
        # empty and re-posts every existing row (a false "wrote" count).
        rows = (data.get("data") or {}).get("rows") or data.get("rows") or []
        return {row.get("slug") for row in rows}
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return set()
        raise


def _post_row(table: str, row: dict, hdr: dict) -> None:
    req = urllib.request.Request(f"{AGENT}/{table}/rows", method="POST",
                                 headers={**hdr, "content-type": "application/json"},
                                 data=json.dumps(row).encode("utf-8"))
    with urllib.request.urlopen(req, timeout=15):
        pass


def absorb(bundle: dict) -> int:
    hdr = {"Authorization": f"Bearer {_rw_token()}", **proxy_header()}
    det = nos_digest.strip_provenance(bundle["deterministic"])
    wrote = skipped = 0
    for table, rows in det.items():   # dependency order (dict preserves it)
        try:
            present = _existing_slugs(table, hdr)
        except (urllib.error.URLError, OSError) as exc:
            print(f"REFUSING: KEAP unreadable ({exc})", file=sys.stderr)
            return 2
        for row in rows:
            if row["slug"] in present:
                print(f"  · {table}/{row['slug']}: already present")
                skipped += 1
                continue
            try:
                _post_row(table, row, hdr)
                print(f"  + {table}/{row['slug']}")
                wrote += 1
            except urllib.error.HTTPError as e:
                print(f"  FAILED {table}/{row['slug']}: {e.code} {e.read().decode()[:120]}",
                      file=sys.stderr)
                return 1
    print(f"\nabsorbed {wrote} · already present {skipped}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", help="path to a CSV of counterparties (legal_name,ico[,trading_name][,country])")
    ap.add_argument("--source-id", help="provenance source id (default: the file name)")
    ap.add_argument("--absorb", action="store_true", help="upsert into KEAP (default is dry: gate + print)")
    ap.add_argument("--out", help="write the gated bundle YAML here (default stdout, when not absorbing)")
    args = ap.parse_args()

    path = pathlib.Path(args.csv)
    if not path.is_absolute():
        path = REPO / path
    raw = path.read_text(encoding="utf-8")
    importer = CsvPartyImporter(args.source_id or path.name)
    bundle, errors = nos_digest.run_importer(importer, raw, TABLES_DIR)

    for s in importer.skipped:
        print(f"skip {s}", file=sys.stderr)
    if errors:
        print("GATE REFUSED the bundle — nothing absorbed:", file=sys.stderr)
        for e in errors:
            print(f"  ✗ {e}", file=sys.stderr)
        return 1

    n = sum(len(v) for v in bundle["deterministic"].values())
    print(f"gate OK: {n} row(s) across {len(bundle['deterministic'])} table(s)"
          f"{'  (DRY)' if not args.absorb else ''}", file=sys.stderr)

    if args.absorb:
        return absorb(bundle)
    text = yaml.safe_dump(bundle, sort_keys=False, allow_unicode=True)
    if args.out:
        (REPO / args.out if not pathlib.Path(args.out).is_absolute() else pathlib.Path(args.out)).write_text(text)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
