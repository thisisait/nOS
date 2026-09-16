#!/usr/bin/env python3
"""Write a REM disposition into ~/.nos/security/dispositions.json.

The generated notebook (remediation-queue.json) is the scanner's. This file
is the operator/agent's, and the scanner must not open it. rem-status.py
joins them at read time.

    tools/rem-dispose.py REM-249 --status resolved --by "SOURCE e617a4ad"
    tools/rem-dispose.py --import-from-queue   # copy closed rows' evidence once

Does not judge. Does not mutate the notebook.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from nos_security import (  # noqa: E402
    DISPOSITION_KEYS,
    dispositions_path,
    load_dispositions,
    queue_path,
    security_dir,
)

CLOSED = ("resolved", "wontfix", "obsolete", "vendor-blocked")


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _save(disp: dict[str, dict]) -> Path:
    path = dispositions_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(disp, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def import_from_queue() -> int:
    qpath = queue_path()
    if not qpath.is_file():
        print(f"UNKNOWN: notebook absent at {qpath}", file=sys.stderr)
        return 2
    raw = json.loads(qpath.read_text(encoding="utf-8"))
    items = raw["items"] if isinstance(raw, dict) and "items" in raw else raw
    disp = load_dispositions()
    added = 0
    for item in items or []:
        rid = item.get("id")
        if not rid or item.get("status") not in CLOSED:
            continue
        if rid in disp:
            continue
        row = {k: item[k] for k in DISPOSITION_KEYS if k in item and item[k] is not None}
        if "status" not in row:
            continue
        disp[rid] = row
        added += 1
    path = _save(disp)
    print(f"{path}: imported {added} closed row(s), {len(disp)} total")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("rem_id", nargs="?", help="REM-NNN")
    ap.add_argument("--status", choices=list(CLOSED) + ["pending"])
    ap.add_argument("--by", dest="resolved_by", default="", help="evidence; required to close")
    ap.add_argument("--import-from-queue", action="store_true",
                    help="copy closed rows' evidence from the notebook into the sidecar")
    args = ap.parse_args()

    if args.import_from_queue:
        return import_from_queue()
    if not args.rem_id or not args.status:
        ap.error("rem_id and --status are required unless --import-from-queue")

    if args.status in CLOSED and not args.resolved_by.strip():
        print("refused: a closed row needs --by evidence", file=sys.stderr)
        return 2

    disp = load_dispositions()
    row = dict(disp.get(args.rem_id) or {})
    row["status"] = args.status
    if args.resolved_by:
        row["resolved_by"] = args.resolved_by
        row["resolved_at"] = _now()
    if args.status == "pending":
        for k in DISPOSITION_KEYS:
            if k != "status":
                row.pop(k, None)
    disp[args.rem_id] = row
    path = _save(disp)
    print(f"{path}: {args.rem_id} -> {args.status}")
    return 0


if __name__ == "__main__":
    # security_dir() is used so a missing HOME still has a target to refuse on.
    if not security_dir():
        sys.exit(2)
    sys.exit(main())
