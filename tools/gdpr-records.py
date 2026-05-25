#!/usr/bin/env python3
"""Emit GDPR Article-30 records as a JSON array (machine-readable sibling of
the human DPA register).

`roles/pazny.wing/tasks/post.yml` runs this to ingest the per-plugin `gdpr:`
blocks into Wing's live `gdpr_processing` table — one `php bin/upsert-gdpr.php
--id=svc_<name>` per record — giving the `/gdpr` UI parity with the static
`state/dpa-register.md`. Both surfaces share the canonical mapper in
`files/anatomy/module_utils/nos_gdpr.py`, so they never diverge.

Usage:
  python3 tools/gdpr-records.py --tier core    # Tier-1 plugins  (svc_*)
  python3 tools/gdpr-records.py --tier app      # Tier-2 manifests (app_*)
  python3 tools/gdpr-records.py --tier all      # both
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "files/anatomy"))
from module_utils import nos_gdpr  # noqa: E401


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tier", choices=["core", "app", "all"], default="core")
    args = ap.parse_args()

    if args.tier == "core":
        recs = nos_gdpr.records_from_plugins(REPO / "files/anatomy/plugins")
    elif args.tier == "app":
        recs = nos_gdpr.records_from_app_manifests(REPO / "apps")
    else:
        recs = nos_gdpr.all_records(REPO)

    json.dump(recs, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
