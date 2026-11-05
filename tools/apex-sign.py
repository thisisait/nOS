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
    tools/apex-sign.py --confirm  # record the new digest and commit ruling.yml (only that file)
    tools/apex-sign.py --show     # the same diff, exit 0: read-only, safe to chain in scripts
    tools/apex-sign.py --repo DIR --confirm   # sign the ruling of another checkout (nos update)

Exit 0 when the ruling already matches its digest (or --show), 1 when it does
not and no --confirm was given, 2 on a usage error.
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
    global REPO, RULING
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--confirm", action="store_true",
                      help="record the digest — do this after reading the diff")
    # 10-29: `apex-sign.py && apex-sign.py --confirm` never reached --confirm (the read exits 1)
    mode.add_argument("--show", action="store_true", help="print the diff and exit 0; never writes")
    ap.add_argument("--repo", type=pathlib.Path, help="the checkout whose ruling to sign")
    args = ap.parse_args()
    if args.repo:
        REPO = args.repo.resolve()
        RULING = REPO / "files/anatomy/apex/ruling.yml"

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

    if args.show:
        return 0
    if not args.confirm:
        print(f"\nrecorded {have[:16]}…\ncomputed {want[:16]}…\n"
              "Read the change above. Then: tools/apex-sign.py --confirm")
        return 1

    RULING.write_text(re.sub(rf"^{FIELD} .*$", f"{FIELD} {want}", text, flags=re.M),
                      encoding="utf-8")
    print(f"signed: {want}")
    rel = RULING.relative_to(REPO)  # the digest counts once committed: twice a push carried the old one
    # only this path, whatever else is staged; the signature is the operator's act, the commit its record
    done = subprocess.run(["git", "-C", str(REPO), "commit", "-q", "-m", "chore(apex): re-sign", "--", str(rel)],
                          capture_output=True, text=True)
    if done.returncode == 0:
        print(f"committed {rel} (chore(apex): re-sign) - push as usual")
    else:
        print(f"\nnot committed ({(done.stderr or done.stdout).strip()[:200]}); record it before any push:\n"
              f"  git add {rel} && git commit -m \"chore(apex): re-sign\" -- {rel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
