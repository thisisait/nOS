#!/usr/bin/env python3
"""The pending REM rows whose recorded fix already runs; with --confirm the operator resolves them.

    tools/rem-retire.py             # reader: candidates, rows below their fix, UNKNOWN; writes nothing, exit 0
    tools/rem-retire.py --confirm   # the operator's: re-reads, then resolves exactly the unchanged candidates

The comparison is discovery-scan's probe B (`read_queue_row`: security_floor before fix_version, numeric
versions only, a prerelease that does not compare is not judged). A row it cannot compare (no running
container, unreadable docker, digest pin, prose fix) is listed apart as UNKNOWN and never written. A
closure goes through tools/rem-dispose.py into dispositions.json, never the notebook, with its evidence
in resolved_by; `tools/rem-dispose.py REM-NNN --status pending` undoes one, and stamps reopened_at: a row the
operator re-opened is listed `reopened`, never a candidate again, until the operator closes it by hand.
Row loop-queue-retires, re-ruled 2026-11-23: never run from a converge, a Pulse job or the loop.
"""
from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("discovery_scan", REPO / "tools/discovery-scan.py")
scan = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = scan  # its dataclasses resolve their module here
_spec.loader.exec_module(scan)
from nos_security import load_dispositions, queue_path  # noqa: E402 — tools/ is on sys.path once the scan module loaded


class _Why:
    """Stands in for discovery-scan's ScanResult: read_queue_row reports why a row cannot be judged here."""
    reason = "not judged"

    def skip(self, reason: str) -> None:
        self.reason = reason


def survey():
    """(candidates, below, unknown, reopened, why-unreadable): candidates map REM id -> (component, QueueReading);
    reopened are the pending rows the operator re-opened (dispositions.json reopened_at), never candidates."""
    if not queue_path().is_file():
        return {}, [], [], [], f"no notebook at {queue_path()}"
    try:
        images = scan.running_images()
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        return {}, [], [], [], f"docker unreadable ({exc.__class__.__name__})"
    disp = load_dispositions()
    cand, below, unknown, reopened = {}, [], [], []
    for item in scan.queue_items():
        if item.get("status") != "pending" or not item.get("id"):
            continue
        if at := (disp.get(str(item["id"])) or {}).get("reopened_at"):
            reopened.append((item["id"], item.get("component") or "?", at))
            continue
        why = _Why()
        r = scan.read_queue_row(item, images, why)
        if r is None:
            unknown.append((item["id"], item.get("component") or "?", why.reason))
        elif r.verdict >= 0:
            cand[item["id"]] = (item.get("component"), r)
        else:
            below.append((item["id"], item.get("component"), r))
    return cand, below, unknown, reopened, None


def show(cand, below, unknown, reopened) -> None:
    for rid, (comp, r) in sorted(cand.items()):
        print(f"retire   {rid}  {comp}  fix {r.fix}  live {r.tag}  ({r.name} {r.image})")
    for rid, comp, r in sorted(below):
        print(f"pending  {rid}  {comp}  fix {r.fix}  live {r.tag} is below it")
    for rid, comp, why in sorted(unknown):
        print(f"UNKNOWN  {rid}  {comp}  {why}")
    for rid, comp, at in sorted(reopened):
        print(f"reopened {rid}  {comp}  by the operator {at}: not retired again until the operator closes it")
    print(f"{len(cand)} to retire, {len(below)} below their fix, {len(unknown)} UNKNOWN, {len(reopened)} reopened")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--confirm", action="store_true", help="resolve the candidates (the operator's act)")
    args = ap.parse_args()
    cand, below, unknown, reopened, unreadable = survey()
    if unreadable:
        print(f"UNKNOWN: {unreadable}; nothing listed, nothing written")
        return 0
    show(cand, below, unknown, reopened)
    if not args.confirm or not cand:
        return 0
    again, _, _, _, unreadable = survey()       # the live versions re-read before any write
    if unreadable:
        print(f"UNKNOWN on the re-read: {unreadable}; nothing written")
        return 1
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    failed = 0
    for rid, (comp, r) in sorted(cand.items()):
        if again.get(rid) != (comp, r):
            print(f"dropped  {rid}: changed since the listing, not written")
            continue
        by = f"live {r.tag} >= fix {r.fix} ({r.image}, {stamp})"
        sys.stdout.flush()                      # keep rem-dispose's own line after the listing
        rc = subprocess.run([sys.executable, str(REPO / "tools/rem-dispose.py"), rid, "--status", "resolved",
                             "--by", by]).returncode
        failed += rc != 0
        print(f"           undo: tools/rem-dispose.py {rid} --status pending")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
