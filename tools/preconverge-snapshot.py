#!/usr/bin/env python3
"""Take the pre-converge snapshot that can be taken; refuse to claim the rest.

WHY THIS EXISTS. `tools/snapshot-status.py` is the reader: it names COVERED
APFS trees (`~/wing` `~/keap` `~/stacks` `~/.nos`) and UNCOVERED HFS+ trees
(`nos_data_root` on the external SSD, RustFS). This file is the preflight that
may ACT — `tmutil localsnapshot` when a Time Machine destination is present,
or an injected alternate path. It never configures Time Machine, never
reformats a volume, and never tells a converge it has a net it does not have.

    tools/preconverge-snapshot.py           # take if claimable; else refuse
    tools/preconverge-snapshot.py --dry-run # verdict only
    tools/preconverge-snapshot.py --json

Exit 0 only when a snapshot was taken (or --dry-run would take one). Exit 1
when the host has no TM destination and no alternate path — that is a
REFUSAL, not an OK with uncovered footnotes.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATUS = HERE / "snapshot-status.py"


def _load_status():
    spec = importlib.util.spec_from_file_location("nos_snapshot_status", STATUS)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {STATUS}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def plan(report: dict, *, dry_run: bool, take) -> dict:
    """Verdict for one reading. `take` is the only writer; tests stub it.

    `ok` is True only when a real mechanism exists AND (dry-run, or the
    take succeeded). APFS coverage alone never sets ok.
    """
    snap = _load_status()
    claim = report.get("claimable") or snap.claimable(
        report.get("prerequisite"), report.get("alternate") or snap.alternate_path())
    covered = report.get("covered") or []
    uncovered = report.get("uncovered") or []
    recovery = report.get("recovery") or snap.RECOVERY
    out = {
        "ok": False,
        "dry_run": dry_run,
        "claimable": claim,
        "taken": False,
        "snapshot": None,
        "covered": [{"path": r["path"], "holds": r.get("holds")} for r in covered],
        "uncovered": [{"path": r["path"], "holds": r.get("holds"),
                       "why": r.get("why")} for r in uncovered],
        "recovery": recovery,
        "why": claim.get("why") or "no snapshot mechanism",
    }
    if claim.get("ok") is not True:
        out["why"] = (
            "REFUSED: no Time Machine destination and no alternate snapshot "
            f"path. {out['why']}"
        )
        return out
    if dry_run:
        out["ok"] = True
        out["why"] = f"dry-run: would snapshot via {claim.get('via')}"
        return out
    result = take(claim)
    out["taken"] = bool(result.get("taken"))
    out["snapshot"] = result.get("name")
    out["why"] = result.get("why") or out["why"]
    out["ok"] = bool(out["taken"])
    return out


def take_tm_localsnapshot(claim: dict) -> dict:
    snap = _load_status()
    if claim.get("via") != "tmutil-localsnapshot":
        return {"taken": False,
                "why": f"no take path for via={claim.get('via')!r}"}
    before = set((snap.snapshots().get("ours") or [])
                 + (snap.snapshots().get("system") or []))
    rc, out = snap._run(["tmutil", "localsnapshot"])
    if rc != 0:
        return {"taken": False,
                "why": f"tmutil localsnapshot rc={rc}: {out[:240]}"}
    after = snap.snapshots()
    names = (after.get("ours") or []) + (after.get("system") or [])
    new = [n for n in names if n not in before]
    return {"taken": True, "name": (new[0] if new else None),
            "why": f"tmutil localsnapshot: {out[:240] or 'ok'}"}


def render(result: dict) -> str:
    word = "OK" if result["ok"] else "REFUSED"
    lines = [f"pre-converge snapshot: {word}", f"  {result['why']}", ""]
    lines.append("covered:")
    if not result["covered"]:
        lines.append("  none")
    for row in result["covered"]:
        lines.append(f"  {row['path']}")
        if row.get("holds"):
            lines.append(f"    {row['holds']}")
    lines.append("uncovered:")
    if not result["uncovered"]:
        lines.append("  none")
    for row in result["uncovered"]:
        lines.append(f"  {row['path']}")
        if row.get("why"):
            lines.append(f"    {row['why']}")
    lines.append("")
    lines.append(f"recovery: {result['recovery']}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--dry-run", action="store_true",
                    help="verdict only; do not call tmutil localsnapshot")
    args = ap.parse_args()

    snap = _load_status()
    result = plan(snap.report(), dry_run=args.dry_run, take=take_tm_localsnapshot)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(render(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
