#!/usr/bin/env python3
"""Sign the apex ruling — after showing what changed since it was last signed.

The ruling decides what this estate says about itself in public. Its signature
used to be a flag (`status: SIGNED` plus a name), which records that someone
once signed something and not that they signed THIS: measured 2026-08-29, a
session amended a SIGNED ruling and every gate stayed green.

So the file now carries `signed_digest`, sha256 over itself with that line
removed, and this is how it is written. The diff comes FIRST and `--confirm` is
a separate act, because a signature that can be given without reading is the
flag again under a longer name.

Usage:
    tools/apex-sign.py            # what changed since the last signature
    tools/apex-sign.py --confirm  # record the new digest

Exit 0 when the ruling already matches its digest, 1 when it does not and no
--confirm was given, 2 on a usage error.
"""

from __future__ import annotations

import argparse
import hashlib
import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
RULING = REPO / "files/anatomy/apex/ruling.yml"
FIELD = "signed_digest:"


def digest(text: str) -> str:
    body = "".join(l for l in text.splitlines(keepends=True) if not l.startswith(FIELD))
    return hashlib.sha256(body.encode()).hexdigest()


def recorded(text: str) -> str | None:
    for line in text.splitlines():
        if line.startswith(FIELD):
            return line.split(":", 1)[1].strip()
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--confirm", action="store_true",
                    help="record the digest — do this after reading the diff")
    args = ap.parse_args()

    if not RULING.is_file():
        print(f"apex-sign: no ruling at {RULING}", file=sys.stderr)
        return 2

    text = RULING.read_text(encoding="utf-8")
    have, want = recorded(text), digest(text)
    if have is None:
        print(f"apex-sign: {RULING.relative_to(REPO)} carries no {FIELD} line; "
              f"add one (any value) and re-run", file=sys.stderr)
        return 2
    if have == want:
        print("the ruling matches its signature — nothing to sign")
        return 0

    # WHAT CHANGED, from git, because the last signature is a commit and the
    # working tree is a claim. A signature offered without the diff is the flag.
    print(f"{RULING.relative_to(REPO)} differs from what was signed.\n")
    for ref in ("HEAD", "origin/dev"):
        out = subprocess.run(["git", "diff", "--stat", ref, "--",
                              str(RULING.relative_to(REPO))],
                             cwd=REPO, capture_output=True, text=True)
        if out.returncode == 0 and out.stdout.strip():
            print(f"against {ref}:")
            print(subprocess.run(["git", "diff", ref, "--",
                                  str(RULING.relative_to(REPO))],
                                 cwd=REPO, capture_output=True, text=True).stdout)
            break
    else:
        print("(no committed version to diff against — read the file itself)")

    if not args.confirm:
        print(f"\nrecorded {have[:16]}…\ncomputed {want[:16]}…\n"
              "Read the change above. Then: tools/apex-sign.py --confirm")
        return 1

    RULING.write_text(re.sub(rf"^{FIELD} .*$", f"{FIELD} {want}", text, flags=re.M),
                      encoding="utf-8")
    print(f"signed: {want}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
