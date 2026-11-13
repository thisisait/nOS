#!/usr/bin/env python3
"""clamav:freshclam: refresh ClamAV's signatures, then judge their age (the cell's heartbeat).

Exit 0: signatures at most MAX_AGE_H old. Exit 11: older, or clamscan cannot say (UNKNOWN).
On Ubuntu the clamav-freshclam daemon owns /var/lib/clamav, so this freshclam run fails there
by design; the age clamscan reports is the verdict either way.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from datetime import datetime

MAX_AGE_H = 48
PATH = os.pathsep.join([os.environ.get("PATH", ""), "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"])
ENV = {**os.environ, "LC_ALL": "C"}


def signature_age_h(version: str, now: datetime) -> float | None:
    """'ClamAV 1.4.1/27456/Wed Nov 12 09:24:01 2025' -> hours since that (local) build time."""
    parts = version.strip().split("/")
    try:
        built = datetime.strptime(parts[2].strip(), "%a %b %d %H:%M:%S %Y")
    except (IndexError, ValueError):
        return None   # no database loaded: clamscan prints the engine version only
    return (now - built).total_seconds() / 3600


def main() -> int:
    fc, cs = shutil.which("freshclam", path=PATH), shutil.which("clamscan", path=PATH)
    if not cs:
        print("clamav: clamscan not found: UNKNOWN", file=sys.stderr)
        return 11
    if fc:
        try:
            r = subprocess.run([fc, "--stdout"], capture_output=True, text=True, timeout=900, env=ENV, check=False)
            print(f"freshclam rc={r.returncode}\n" + "\n".join(r.stdout.splitlines()[-5:]))
        except (OSError, subprocess.TimeoutExpired) as exc:
            print(f"freshclam did not finish: {type(exc).__name__}", file=sys.stderr)
    try:
        version = subprocess.run([cs, "--version"], capture_output=True, text=True, timeout=60,
                                 env=ENV, check=False).stdout
    except (OSError, subprocess.TimeoutExpired):
        version = ""
    age = signature_age_h(version, datetime.now())
    print(f"clamav signatures: {version.strip() or 'no answer'} · age {'UNKNOWN' if age is None else f'{age:.1f} h'}")
    return 0 if age is not None and age <= MAX_AGE_H else 11


if __name__ == "__main__":
    sys.exit(main())
