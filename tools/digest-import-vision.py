#!/usr/bin/env python3
"""digest-import-vision — the invoice-vision-intake unit: VisionImporter(IsdocImporter).

The FOURTH digest importer, and the vision half of the invoice critical path.
Overrides ONLY parse(): globs *.extract.json sidecars (the invoice-structured-
extractor unit's output — per-field {value, confidence, source} + a top-level
`verified`, state/schema/isdoc-extract-sidecar.schema.yaml) into the SAME
record-dict shape IsdocImporter.parse() produces, so normalize() / compose() /
_resolve() (dual-party resolve, book_owner stamping) are inherited verbatim —
never reimplemented.

THE OPERATOR-VERIFY RUNG IS parse() ITSELF: nos_digest documents that a
party-review rung "lands with repos-importer", which has NOT shipped (grep:
zero hits) — there is no separate rung for a whole invoice either. So a
sidecar with verified!=True, or ANY field below CONFIDENCE_FLOOR, is appended
to self.skipped right here and NEVER becomes a candidate record — structurally
identical to IsdocImporter's unknown-buyer skip. An unverified or
low-confidence invoice can therefore never reach absorb.

  tools/digest-import-vision.py state/fixtures/vision-fixture --fixture-mode
  tools/digest-import-vision.py state/fixtures/vision-fixture --fixture-mode --absorb

DRY by default. Exit 0 · 1 gate refused · 2 KEAP unreadable.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import pathlib
import sys
import urllib.error

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "files" / "anatomy" / "module_utils"))
from digest_absorb import absorb, build_party_index  # noqa: E402
import nos_digest  # noqa: E402

TABLES_DIR = REPO / "state" / "keap-tables"
SIDECAR_SCHEMA = yaml.safe_load(
    (REPO / "state" / "schema" / "isdoc-extract-sidecar.schema.yaml").read_text(encoding="utf-8"))
#: The ONE place this number is spelled — read from the schema doc, not
#: repeated as a literal, so the doc and the enforcement cannot drift apart.
CONFIDENCE_FLOOR = float(SIDECAR_SCHEMA["confidence_floor"])


def _load_isdoc_importer():
    """digest-import-isdoc.py is not import-able by name (dash in the
    filename) — the same load-by-path every test file for it already uses."""
    spec = importlib.util.spec_from_file_location(
        "digest_import_isdoc", REPO / "tools" / "digest-import-isdoc.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.IsdocImporter


IsdocImporter = _load_isdoc_importer()


class VisionImporter(IsdocImporter):
    """Vision-extracted invoices → the invoice facet. Overrides ONLY parse();
    normalize/compose/_resolve (dual-party resolve, book_owner) are inherited."""

    name = "isdoc-vision"
    version = "0.1.0"

    def parse(self, root) -> list[dict]:
        root = pathlib.Path(root)
        out = []
        for f in sorted(root.glob("*.extract.json")):
            try:
                sidecar = json.loads(f.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                self.skipped.append(f"{f.name}: unreadable sidecar ({exc})")
                continue
            record = sidecar.get("record") if isinstance(sidecar, dict) else None
            fields = sidecar.get("fields") if isinstance(sidecar, dict) else None
            if not isinstance(record, dict) or not isinstance(fields, dict):
                self.skipped.append(f"{f.name}: sidecar missing record/fields")
                continue
            low = sorted(k for k, v in fields.items()
                        if not isinstance(v, dict) or v.get("confidence", 0) < CONFIDENCE_FLOOR)
            verified = sidecar.get("verified") is True
            # THE OPERATOR-VERIFY RUNG: unverified OR any field under the floor
            # never becomes a record — no auto-pass on partial confidence.
            if not verified or low:
                reason = "not operator-verified" if not verified else f"low-confidence field(s) {low}"
                self.skipped.append(
                    f"{f.name}: {reason} (floor {CONFIDENCE_FLOOR}) — operator-verify rung, "
                    "routed to review, never absorbed")
                continue
            if not record.get("id"):
                self.skipped.append(f"{f.name}: verified sidecar has no invoice id")
                continue
            rec = dict(record)
            rec["file"] = f.name
            rec.setdefault("seller", {})
            rec.setdefault("buyer", {})
            out.append(rec)
        return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", help="a directory of *.extract.json vision sidecars")
    ap.add_argument("--source-id")
    ap.add_argument("--absorb", action="store_true", help="upsert into KEAP (default dry)")
    ap.add_argument("--out", help="write the gated bundle YAML here (default stdout, dry)")
    ap.add_argument("--fixture-mode", action="store_true",
                    help="resolve synthetic-range IČOs (000001xx) — for the fixture spine only")
    ap.add_argument("--book-owner-ico",
                    help="IČO of the client this import run is FOR (data-org attribute, "
                         "stamped as invoice.book_owner; resolved, never minted)")
    args = ap.parse_args()

    root = pathlib.Path(args.root)
    if not root.is_absolute():
        root = REPO / root
    try:
        index = build_party_index()
    except (urllib.error.URLError, OSError) as exc:
        print(f"REFUSING: cannot build party index from KEAP ({exc})", file=sys.stderr)
        return 2

    importer = VisionImporter(args.source_id or root.name, index, fixture_mode=args.fixture_mode,
                              book_owner_ico=args.book_owner_ico)
    bundle, errors = nos_digest.run_importer(importer, str(root), TABLES_DIR)

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
    out = args.out and (REPO / args.out if not pathlib.Path(args.out).is_absolute()
                        else pathlib.Path(args.out))
    out.write_text(text) if out else print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
