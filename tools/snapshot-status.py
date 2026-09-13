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
EXTERNAL_ROOT_VAR = "external_storage_root"

#: A snapshot this estate made, as opposed to one macOS made for its own update.
NOS_SNAPSHOT = re.compile(r"^nos-preconverge-")

#: Restore is a RO mount of the named snapshot plus a copy. It is not a
#: bootloader rollback (no `bless`, no boot into the snap).
RECOVERY = (
    "A snapshot is not a bootloader undo. Restore with "
    "`mount_apfs -s <snapshot> -o rdonly <device> <mountpoint>` "
    "then copy the guarded trees back. UNCOVERED paths are not in that net; "
    "they recover from backup, if at all."
)

TIMEOUT = 30


def _run(argv: list[str]) -> tuple[int, str]:
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=TIMEOUT)
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, str(exc)
    return p.returncode, (p.stdout or p.stderr).strip()


def _config_scalar(key: str) -> str | None:
    for path in (REPO / "config.yml", REPO / "default.config.yml"):
        if not path.exists():
            continue
        m = re.search(rf"^{re.escape(key)}:\s*[\"']?([^\"'#\n]+)",
                      path.read_text(encoding="utf-8"), re.M)
        if m:
            return m.group(1).strip()
    return None


def _expand_home_jinja(raw: str) -> str | None:
    """Expand the one HOME token we know; refuse any other Jinja."""
    if "{{" not in raw:
        return raw
    expanded = re.sub(
        r"\{\{\s*ansible_facts\['env'\]\['HOME'\]\s*\}\}", str(HOME), raw)
    if "{{" in expanded:
        return None
    return expanded


def data_root() -> pathlib.Path | None:
    """nos_data_root from config.yml, then the default, then the live SSD tree.

    config.yml is gitignored and overrides the committed default; reading only
    the default would report the wrong volume on exactly the estate this file
    was written for. When the configured path is absent, a mounted
    `{external_storage_root}/nOS/data` is the running-system answer — the repo
    is not the estate.
    """
    raw = _config_scalar(DATA_ROOT_VAR)
    parsed = None
    if raw:
        expanded = _expand_home_jinja(raw)
        if expanded:
            parsed = pathlib.Path(expanded)
            if parsed.exists():
                return parsed
    ext = _config_scalar(EXTERNAL_ROOT_VAR)
    if ext and "{{" not in ext:
        live = pathlib.Path(ext) / "nOS" / "data"
        if live.exists():
            return live
    return parsed


def rustfs_root() -> pathlib.Path | None:
    root = data_root()
    if root is None:
        return None
    return root / "platform" / "services" / "rustfs" / "data"


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


def alternate_path() -> dict:
    """A snapshot facility that is not Time Machine.

    Stock macOS has none we are willing to claim: `diskutil apfs snapshot` on
    the SIP-protected Data volume is not an operator path, and inventing one
    here would be the net this file exists to refuse to fake. Tests inject a
    positive result; production stays honest.
    """
    return {"ok": False, "via": None,
            "why": "no Time-Machine-independent snapshot path is configured"}


def claimable(pre: dict | None = None, alt: dict | None = None) -> dict:
    """True only when a real snapshot mechanism exists. Never inferred from APFS."""
    pre = prerequisite() if pre is None else pre
    alt = alternate_path() if alt is None else alt
    if pre.get("ok") is True:
        return {"ok": True, "via": "tmutil-localsnapshot", "why": pre["why"],
                "prerequisite": pre, "alternate": alt}
    if alt.get("ok") is True:
        return {"ok": True, "via": alt.get("via") or "alternate", "why": alt["why"],
                "prerequisite": pre, "alternate": alt}
    if pre.get("ok") is None and not alt.get("ok"):
        return {"ok": None, "via": None, "why": pre.get("why") or "unreadable",
                "prerequisite": pre, "alternate": alt}
    why = pre.get("why") or "no snapshot mechanism"
    if alt.get("why"):
        why = f"{why}; {alt['why']}"
    return {"ok": False, "via": None, "why": why,
            "prerequisite": pre, "alternate": alt}


def coverage_rows() -> list[dict]:
    rows = [dict(volume_of(p), holds=holds) for p, holds in GUARDED]
    root = data_root()
    if root is not None:
        rows.append(dict(volume_of(root),
                         holds="every redirected service data dir (nos_data_root)",
                         is_data_root=True))
        rustfs = rustfs_root()
        if rustfs is not None:
            rows.append(dict(volume_of(rustfs),
                             holds="RustFS object store (backup copy #1)",
                             is_rustfs=True))
    return rows


def split_coverage(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    covered = [r for r in rows if r.get("snapshottable") is True]
    uncovered = [r for r in rows if r.get("snapshottable") is not True]
    return covered, uncovered


def report() -> dict:
    rows = coverage_rows()
    covered, uncovered = split_coverage(rows)
    pre = prerequisite()
    claim = claimable(pre, alternate_path())
    return {"generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "prerequisite": pre, "claimable": claim, "snapshots": snapshots(),
            "coverage": rows, "covered": covered, "uncovered": uncovered,
            "recovery": RECOVERY}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    r = report()
    if args.json:
        print(json.dumps(r, indent=2))
        return 0

    claim = r["claimable"]
    mark = {True: "yes", False: "NO", None: "UNKNOWN"}[claim["ok"]]
    print(f"pre-converge snapshot capability: {mark}")
    print(f"  {claim['why']}")
    pre = r["prerequisite"]
    tm = {True: "yes", False: "NO", None: "UNKNOWN"}[pre["ok"]]
    print(f"  Time Machine destination: {tm}")
    alt = claim["alternate"]
    print(f"  alternate snapshot path: "
          f"{'yes — ' + (alt.get('via') or '') if alt.get('ok') else 'NO'}\n")

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

    print("\ncovered (APFS — in the snapshot IF a net existed):")
    if not r["covered"]:
        print("  none")
    for row in r["covered"]:
        print(f"  COVERED   {row['path']}")
        print(f"            {row['holds']}")
        print(f"            {row['why']}")

    print("\nuncovered (named so nobody reads a snapshot as full coverage):")
    if not r["uncovered"]:
        print("  none")
    for row in r["uncovered"]:
        state = {True: "COVERED  ", False: "UNCOVERED", None: "UNKNOWN  "}[row["snapshottable"]]
        print(f"  {state} {row['path']}")
        print(f"            {row['holds']}")
        print(f"            {row['why']}")

    if r["uncovered"]:
        print(f"\n  {len(r['uncovered'])} guarded path(s) NOT covered. A snapshot taken "
              "here is a partial net, and the parts it misses are named above — "
              "do not read 'snapshot taken' as 'everything is recoverable'.")
    print(f"\nrecovery: {r['recovery']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
