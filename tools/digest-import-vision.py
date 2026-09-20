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
import os
import pathlib
import sys
import urllib.error

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "files" / "anatomy" / "module_utils"))
from digest_absorb import absorb, build_party_index  # noqa: E402
import nos_digest  # noqa: E402
import raw_archive  # noqa: E402

TABLES_DIR = REPO / "state" / "keap-tables"
RETENTION_DAYS = yaml.safe_load(
    (REPO / "state" / "digest-importers" / "isdoc-vision.importer.yml").read_text(encoding="utf-8")
)["gdpr"]["retention_days"]
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


def index_pending(rows) -> dict:
    """Join key is sidecar_id (filename), never slug. Shared by the KEAP
    read and injectable fake rows so parse() cannot silently match the PK."""
    return {r["sidecar_id"]: r.get("resolution") for r in rows if r.get("sidecar_id")}


class VisionImporter(IsdocImporter):
    """Vision-extracted invoices → the invoice facet. Overrides ONLY parse();
    normalize/compose/_resolve (dual-party resolve, book_owner) are inherited."""

    name = "isdoc-vision"
    version = "0.1.0"
    #: provenance-keep unit: rows this importer composes are OCR-sourced.
    source_kind = "vision"

    def __init__(self, *args, pending_verify: dict[str, str] | list | None = None, **kwargs):
        """``pending_verify``: {sidecar_id: resolution} or a list of pending
        rows (indexed by sidecar_id, never slug). ``None`` looks the table
        up from KEAP on first use; a network failure degrades to {} (held)."""
        super().__init__(*args, **kwargs)
        if isinstance(pending_verify, list):
            self._pending_verify = index_pending(pending_verify)
        else:
            self._pending_verify = pending_verify

    def _pending_resolution(self, sidecar_id: str) -> str | None:
        if self._pending_verify is None:
            try:
                import digest_absorb
                self._pending_verify = index_pending(
                    digest_absorb.read_rows("pending-invoice-verify"))
            except Exception:  # noqa: BLE001 — unreachable KEAP == no pending rows == held
                self._pending_verify = {}
        return self._pending_verify.get(sidecar_id)

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
            # provenance-keep unit: the row-level survivor is the MIN across every
            # field's confidence — the floor this sidecar actually cleared — not
            # the full per-field breakdown (that stays disposable, in
            # pending-invoice-verify.fields for the ones that needed review).
            confidences = [v.get("confidence") for v in fields.values()
                          if isinstance(v, dict) and isinstance(v.get("confidence"), (int, float))]
            overall_confidence = round(min(confidences), 4) if confidences else None
            verified = sidecar.get("verified") is True
            # D5 verify-write-back: a consultant's PRIOR decision on this exact
            # sidecar (keyed on the filename — the join key, stable even when
            # `record` has no id). approved -> treat as verified regardless of
            # raw confidence; rejected -> a DURABLE tombstone, never re-offered
            # (checked before the raw verified/low-confidence gate below, so a
            # rejected sidecar stays out across every future run, not just one).
            resolution = self._pending_resolution(f.name)
            if resolution == "rejected":
                self.skipped.append(f"{f.name}: rejected in pending-invoice-verify — permanent tombstone")
                continue
            if resolution == "approved":
                verified, low = True, []
            # THE OPERATOR-VERIFY RUNG: unverified OR any field under the floor
            # never becomes a record — no auto-pass on partial confidence.
            elif not verified or low:
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
            rec["verified"] = verified
            rec["overall_confidence"] = overall_confidence
            # raw-archive-store unit: archives the SIDECAR itself — the true
            # originating image/PDF lives in incoming/, one directory over,
            # and this importer never reads it (design ceiling: archiving the
            # real original needs wiring through the invoice-vision-ocr agent
            # that PRODUCES this sidecar, not this importer).
            rec["raw_archive_ref"] = raw_archive.archive_put(
                "invoice", f.read_bytes(), retain_days=RETENTION_DAYS)
            out.append(rec)
        return out


def discover_extracts(root: pathlib.Path) -> list[pathlib.Path]:
    """Pulse cannot glob. Walks tenants/*/.../accounting/*/extracts."""
    return sorted(p for p in root.glob(
        "tenants/*/users/*/inbox/accounting/*/extracts") if p.is_dir())


def _roots(root_arg: str | None) -> list[pathlib.Path]:
    if root_arg:
        root = pathlib.Path(root_arg)
        return [root if root.is_absolute() else REPO / root]
    return discover_extracts(pathlib.Path(
        os.environ.get("NOS_DATA_ROOT") or pathlib.Path.home() / "nos"))


def _run_one(root: pathlib.Path, args, index) -> int:
    importer = VisionImporter(args.source_id or root.name, index, fixture_mode=args.fixture_mode,
                              book_owner_ico=args.book_owner_ico,
                              book_owner_slug_hint=nos_digest.infer_book_owner_slug(root))
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
        return 0 if n == 0 else absorb(bundle)
    text = yaml.safe_dump(bundle, sort_keys=False, allow_unicode=True)
    out = args.out and (REPO / args.out if not pathlib.Path(args.out).is_absolute()
                        else pathlib.Path(args.out))
    out.write_text(text) if out else print(text)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", nargs="?",
                    help="a directory of *.extract.json vision sidecars; "
                         "omit to walk every per-client extracts/ (Pulse absorb-approved)")
    ap.add_argument("--source-id")
    ap.add_argument("--absorb", action="store_true", help="upsert into KEAP (default dry)")
    ap.add_argument("--out", help="write the gated bundle YAML here (default stdout, dry)")
    ap.add_argument("--fixture-mode", action="store_true",
                    help="resolve synthetic-range IČOs (000001xx) — for the fixture spine only")
    ap.add_argument("--book-owner-ico",
                    help="IČO of the client this import run is FOR (data-org attribute, "
                         "stamped as invoice.book_owner; resolved, never minted)")
    args = ap.parse_args()

    roots = _roots(args.root)
    if not roots:
        print("no extracts/ dirs — nothing to absorb", file=sys.stderr)
        return 0
    if args.out and len(roots) > 1:
        print("REFUSING: --out with multiple extracts/ dirs; pass one root", file=sys.stderr)
        return 2
    try:
        index = build_party_index()
    except (urllib.error.URLError, OSError) as exc:
        print(f"REFUSING: cannot build party index from KEAP ({exc})", file=sys.stderr)
        return 2

    worst = 0
    for root in roots:
        rc = _run_one(root, args, index)
        if rc == 2:
            return 2
        worst = max(worst, rc)
    return worst


if __name__ == "__main__":
    sys.exit(main())
