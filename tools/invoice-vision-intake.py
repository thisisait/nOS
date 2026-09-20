#!/usr/bin/env python3
"""invoice-vision-intake — the Pulse-job body behind files/anatomy/plugins/
invoice-vision-base/plugin.yml.

Pulse cannot glob a directory or pass space-bearing paths as args, so the batch
loop lives here (one tools/*.py, which auto-passes the command allowlist). On a
cadence it sweeps the invoice intake dir:

  <intake>/incoming/*.{pdf,jpg,jpeg,png}
     -> tools/invoice-vision-pipeline.py <img> --out <intake>/extracts/<stem>.extract.json
     -> for every HELD sidecar (verified:false or any field < CONFIDENCE_FLOOR),
        UPSERT a `pending-invoice-verify` row so the consultant has a real queue.

This closes the "reader with no writer" gap (adversarial review #2 / dtt
verify-writeback-needs-writer): VisionImporter.parse() READS pending-invoice-verify
but nothing WROTE it, so a below-floor sidecar existed only as an inert file. Now
the sweep populates the queue. Booking stays a later, deliberate step: an operator
approves rows via tools/invoice-verify.py (resolution=approved, HMAC-audited),
and a `digest-import-vision --absorb` run honors it (the table's own batch
semantics — approval posts nothing by itself). That absorb run is itself
manual/unscheduled today — this job fills the queue; it does NOT book.

Idempotent: an image whose sidecar already exists is not re-extracted; a queue row
whose slug already exists is not re-posted. Read-only w.r.t. the invoice/party
tables — it only ever writes pending-invoice-verify.

Exit: 0 swept, nothing held · 1 swept, N invoices need operator verify (a finding,
declared in the plugin's findings_exit_codes) · 2 could not run (no intake dir, or
every extraction failed — e.g. qwen2.5vl:7b not pulled / ollama not armed).
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import subprocess
import sys
import urllib.error

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "files" / "anatomy" / "module_utils"))
import digest_absorb  # noqa: E402  (reuse the ONE KEAP write path)
from keap_api import proxy_header  # noqa: E402
import yaml  # noqa: E402

PIPELINE = REPO / "tools" / "invoice-vision-pipeline.py"
SCHEMA = REPO / "state" / "schema" / "isdoc-extract-sidecar.schema.yaml"
CONFIDENCE_FLOOR = float(yaml.safe_load(SCHEMA.read_text(encoding="utf-8"))["confidence_floor"])
TABLE = "pending-invoice-verify"
IMAGE_EXT = (".pdf", ".jpg", ".jpeg", ".png")


def is_held(sidecar: dict, floor: float = CONFIDENCE_FLOOR) -> bool:
    """The SAME gate VisionImporter.parse() applies: a sidecar is held for
    operator verify unless it is verified AND every field is at/above the floor.
    Pure → testable without a model or KEAP."""
    if sidecar.get("verified") is not True:
        return True
    for f in (sidecar.get("fields") or {}).values():
        if not isinstance(f, dict) or float(f.get("confidence", 0.0)) < floor:
            return True                    # a malformed field is held, never crashes (matches parse())
    return False


def _slug(name: str) -> str:
    return "piv-" + re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", name.lower())).strip("-")


def verify_row(sidecar_name: str, sidecar: dict) -> dict:
    """The pending-invoice-verify row for a held sidecar. sidecar_id is the STABLE
    JOIN KEY VisionImporter.parse() looks up by (the sidecar filename). Pure."""
    return {"slug": _slug(sidecar_name), "sidecar_id": sidecar_name,
            "fields": sidecar.get("fields") or {}, "resolution": "pending"}


def _extract_one(image: pathlib.Path, out: pathlib.Path) -> bool:
    if out.exists():
        return True                                    # idempotent — already extracted
    r = subprocess.run([sys.executable, str(PIPELINE), str(image), "--out", str(out)],
                       capture_output=True, text=True)
    if r.returncode != 0 or not out.exists():
        print(f"  extract failed {image.name} (exit {r.returncode}): {r.stderr[-200:]}", file=sys.stderr)
        return False
    return True


def discover_intakes(root: pathlib.Path) -> list[pathlib.Path]:
    """Every per-client incoming/ under the runtime tenants tree
    (<root>/tenants/<t>/users/<uid>/inbox/accounting/<book_owner>/incoming) —
    the storage-subdir convention (nos_digest.infer_book_owner_slug). A Pulse
    job cannot glob, so the sweep discovers them here."""
    return sorted(p for p in root.glob("tenants/*/users/*/inbox/accounting/*/incoming") if p.is_dir())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--intake", default=None,
                    help="a single dir with incoming/ (images) + extracts/ (sidecars); "
                         "default walks every per-client incoming/ under the tenants tree")
    ap.add_argument("--root", default=os.environ.get("NOS_DATA_ROOT") or str(pathlib.Path.home() / "nos"),
                    help="data root to walk for per-client incoming/ dirs (NOS_DATA_ROOT or ~/nos). "
                         "ponytail: honours a non-default nos_data_root only via NOS_DATA_ROOT env")
    args = ap.parse_args()

    if args.intake:
        d = pathlib.Path(args.intake)
        incomings = [d / "incoming" if (d / "incoming").is_dir() else d]
    else:
        incomings = discover_intakes(pathlib.Path(args.root))
    if not incomings:
        print(f"REFUSING: no intake incoming/ dirs under {args.intake or args.root}", file=sys.stderr)
        return 2

    imgs = [(inc, p) for inc in incomings for p in sorted(inc.glob("*")) if p.suffix.lower() in IMAGE_EXT]
    if not imgs:
        print(f"no intake images under {args.intake or args.root} — nothing to sweep", file=sys.stderr)
        return 0

    extract_dirs = set()
    extracted = 0
    for inc, img in imgs:
        extracts = inc.parent / "extracts"
        extracts.mkdir(parents=True, exist_ok=True)
        extract_dirs.add(extracts)
        if _extract_one(img, extracts / f"{img.stem}.extract.json"):
            extracted += 1
    if extracted == 0:
        print("REFUSING: every extraction failed — is qwen2.5vl:7b pulled and ollama armed?", file=sys.stderr)
        return 2

    # populate the operator-verify queue for held sidecars (idempotent upsert)
    hdr = {"Authorization": f"Bearer {digest_absorb.rw_token()}", **proxy_header()}
    try:
        digest_absorb.ensure_table(TABLE, hdr)
        present = {r.get("slug") for r in digest_absorb.read_rows(TABLE)}
    except (urllib.error.URLError, OSError) as exc:
        print(f"REFUSING: KEAP unreadable ({exc})", file=sys.stderr)
        return 2

    held = queued = 0
    sidecars = sorted(sc for ed in extract_dirs for sc in ed.glob("*.extract.json"))
    for sc_path in sidecars:
        sidecar = json.loads(sc_path.read_text(encoding="utf-8"))
        if not is_held(sidecar):
            continue
        held += 1
        row = verify_row(sc_path.name, sidecar)
        if row["slug"] in present:
            print(f"  · {row['slug']}: already queued")
            continue
        try:
            digest_absorb._post_row(TABLE, row, hdr)
            print(f"  + queued {row['slug']} ({sc_path.name})")
            queued += 1
        except urllib.error.HTTPError as e:
            print(f"  FAILED queue {row['slug']}: {e.code} {e.read().decode()[:160]}", file=sys.stderr)
            return 2

    print(f"\nswept {len(imgs)} image(s), extracted {extracted}, held {held}, newly queued {queued}")
    return 1 if held else 0            # held == a finding (invoices await operator verify)


if __name__ == "__main__":
    raise SystemExit(main())
