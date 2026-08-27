#!/usr/bin/env python3
"""Is there a net under the next converge, and what exactly does it hold?

WHY THIS EXISTS. Omarchy takes a snapper snapshot before every update and keeps
five, so a bad update is one reboot from undone. nOS has backups — 14 sources,
a restic copy on the external SSD, and a restore drill that genuinely replays
them rather than checking a file exists — but nothing atomic, nothing at
converge granularity, and no single reading that says whether a net is present
right now.

This is that reading. It creates nothing, deletes nothing, and exits 0 whatever
it finds.

    tools/snapshot-status.py
    tools/snapshot-status.py --json

WHAT THE ESTATE MEASURED, 2026-08-27, and why the answer is not a simple yes:

    ~/wing  ~/keap  ~/stacks  ~/.nos   /dev/disk3s5  APFS Data volume   snapshottable
    /Volumes/SSD1TB/nOS/data           /dev/disk7s2  Journaled HFS+     CANNOT be

`nos_data_root` — the external SSD holding every redirected service data dir and
RustFS backup copy #1 — is HFS+, and HFS+ has no snapshots. So a snapshot here
covers the loop ledger, the WORM audit chain and the KEAP knowledge DB, and does
NOT cover the data volume. Reformatting SSD1TB to APFS would close that; it is
the operator's call and not something a converge should imply it has done.

**That split is the whole reason this file prints coverage rather than a tick.**
A converge that believes it has a net and does not is worse than one that knows
it has none — `docs/hidden_fees/08` is the same shape one layer down, where a
stack with no containers read as ready.

THE PREREQUISITE, also measured 2026-08-27 and also not a yes: `tmutil
destinationinfo` on this host says *No destinations configured*, and the only
local snapshots present are `com.apple.os.update-*` written by macOS itself.
Whether `tmutil localsnapshot` will produce anything without a Time Machine
destination is reported here as a PROBE RESULT, never assumed — and if it
cannot, the honest output is that the estate has no pre-converge net, with the
reason, rather than a silent zero.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
HOME = pathlib.Path(os.path.expanduser("~"))

#: The paths whose loss would cost something git cannot give back, and what
#: each one holds. Ordered by what it would hurt most to lose.
GUARDED = [
    (HOME / "wing", "the loop ledger, its WORM verdict chain, the Wing inbox, "
                    "agent session history"),
    (HOME / "keap", "the KEAP knowledge DB, captures, the review queue, embeddings"),
    (HOME / ".nos", "runtime secrets, state.yml, backup-status.json"),
    (HOME / "stacks", "rendered compose files and role overrides"),
]

#: Resolved from default.config.yml rather than assumed, because on this estate
#: it is redirected to external storage and that is the whole finding.
DATA_ROOT_VAR = "nos_data_root"

#: A snapshot this estate made, as opposed to one macOS made for its own update.
NOS_SNAPSHOT = re.compile(r"^nos-preconverge-")

TIMEOUT = 30


def _run(argv: list[str]) -> tuple[int, str]:
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=TIMEOUT)
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, str(exc)
    return p.returncode, (p.stdout or p.stderr).strip()


def data_root() -> pathlib.Path | None:
    """What config.yml resolves nos_data_root to, falling back to the default.

    config.yml is gitignored and overrides the committed default; reading only
    the default would report the wrong volume on exactly the estate this file
    was written for.
    """
    for path in (REPO / "config.yml", REPO / "default.config.yml"):
        if not path.exists():
            continue
        m = re.search(rf"^{DATA_ROOT_VAR}:\s*[\"']?([^\"'#\n]+)",
                      path.read_text(encoding="utf-8"), re.M)
        if m and "{{" not in m.group(1):
            return pathlib.Path(m.group(1).strip())
    return None


def volume_of(path: pathlib.Path) -> dict:
    """Device, mount point and filesystem for a path — and whether APFS."""
    row = {"path": str(path), "exists": path.exists()}
    if not path.exists():
        row["fs"] = None
        row["snapshottable"] = None          # UNKNOWN, not False
        row["why"] = "path absent — nothing to say about its volume"
        return row
    rc, out = _run(["/bin/df", "-P", str(path)])
    if rc != 0 or len(out.splitlines()) < 2:
        row["fs"], row["snapshottable"] = None, None
        row["why"] = "df could not read this path"
        return row
    fields = out.splitlines()[-1].split()
    row["device"], row["mount"] = fields[0], fields[-1]
    rc, info = _run(["diskutil", "info", row["device"]])
    m = re.search(r"File System Personality:\s*(.+)", info) if rc == 0 else None
    row["fs"] = m.group(1).strip() if m else None
    if row["fs"] is None:
        row["snapshottable"] = None
        row["why"] = "diskutil could not name the filesystem — UNKNOWN, not 'no'"
    else:
        row["snapshottable"] = "apfs" in row["fs"].lower()
        row["why"] = ("APFS — snapshots are possible on this volume"
                      if row["snapshottable"]
                      else f"{row['fs']} has no snapshot facility")
    return row


def snapshots() -> dict:
    """Local snapshots on the Data volume, split into ours and the system's."""
    if not shutil.which("tmutil"):
        return {"available": False, "why": "tmutil absent (not macOS?)",
                "ours": [], "system": []}
    rc, out = _run(["tmutil", "listlocalsnapshots", "/System/Volumes/Data"])
    if rc != 0:
        return {"available": False, "why": f"tmutil listlocalsnapshots rc={rc}: {out[:160]}",
                "ours": [], "system": []}
    names = [ln.strip() for ln in out.splitlines()[1:] if ln.strip()]
    return {"available": True, "why": "",
            "ours": [n for n in names if NOS_SNAPSHOT.match(n)],
            "system": [n for n in names if not NOS_SNAPSHOT.match(n)]}


def prerequisite() -> dict:
    """Can this host make a local snapshot at all?

    PROBED, not assumed, and the probe is read-only: `tmutil destinationinfo`
    reports whether Time Machine has a destination, which is the documented
    precondition for `tmutil localsnapshot`. This file does NOT run
    `localsnapshot` to find out — creating one to learn whether you can create
    one is a side effect a reader may not have.
    """
    if not shutil.which("tmutil"):
        return {"ok": None, "why": "tmutil absent — not a macOS host"}
    rc, out = _run(["tmutil", "destinationinfo"])
    configured = rc == 0 and "no destinations" not in out.lower()
    return {"ok": configured,
            "why": ("a Time Machine destination is configured" if configured else
                    "tmutil reports no Time Machine destination; `tmutil "
                    "localsnapshot` is documented to need one, so a pre-converge "
                    "snapshot cannot be assumed to work here until it is probed "
                    "by an actual attempt")}


def report() -> dict:
    rows = [dict(volume_of(p), holds=holds) for p, holds in GUARDED]
    root = data_root()
    if root is not None:
        rows.append(dict(volume_of(root), holds="every redirected service data "
                                                "dir and RustFS backup copy #1",
                         is_data_root=True))
    return {"generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "prerequisite": prerequisite(), "snapshots": snapshots(), "coverage": rows}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    r = report()
    if args.json:
        print(json.dumps(r, indent=2))
        return 0

    pre = r["prerequisite"]
    mark = {True: "yes", False: "NO", None: "UNKNOWN"}[pre["ok"]]
    print(f"pre-converge snapshot capability: {mark}")
    print(f"  {pre['why']}\n")

    snaps = r["snapshots"]
    if not snaps["available"]:
        print(f"  snapshots UNREADABLE — {snaps['why']}")
    else:
        print(f"  nOS pre-converge snapshots: {len(snaps['ours'])}")
        for n in snaps["ours"][:5]:
            print(f"    {n}")
        if not snaps["ours"]:
            print("    none — the estate has never taken one")
        print(f"  macOS system snapshots present: {len(snaps['system'])} "
              "(these are not a net for nOS data)")

    print("\ncoverage, if a snapshot were taken now:")
    uncovered = []
    for row in r["coverage"]:
        state = {True: "COVERED  ", False: "UNCOVERED", None: "UNKNOWN  "}[row["snapshottable"]]
        print(f"  {state} {row['path']}")
        print(f"            {row['holds']}")
        print(f"            {row['why']}")
        if row["snapshottable"] is not True:
            uncovered.append(row["path"])

    if uncovered:
        print(f"\n  {len(uncovered)} guarded path(s) NOT covered. A snapshot taken "
              "here is a partial net, and the parts it misses are named above — "
              "do not read 'snapshot taken' as 'everything is recoverable'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
