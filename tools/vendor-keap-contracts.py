#!/usr/bin/env python3
"""Re-vendor KEAP's DataTable schema into the face, pinned to keap_repo_ref.

The schema-pin gate (files/anatomy/face/src/lib/keap-contracts/schema-pin.test.ts)
validates every state/keap-tables/*.table.yml against KEAP's OWN zod schema. That
schema is not nOS's to author — it is VENDORED, and it must be vendored at the
tag the estate runs, never dev HEAD (a def valid only against an unreleased
schema is the caddy-sessions incident the gate exists to prevent).

This copies the three self-contained contract files from the KEAP source clone
(~/keap/src, which roles/pazny.keap checks out AT keap_repo_ref during a
converge) into the vendor dir, stamping each with the pin. Run it after bumping
keap_repo_ref and re-converging (or after `git -C ~/keap/src checkout <tag>`):

    tools/vendor-keap-contracts.py            # vendor from ~/keap/src at the pin
    tools/vendor-keap-contracts.py --check    # fail if the vendored copy is stale

It does NOT fetch or checkout — it trusts the clone's current tree, and prints
the pin it read so a mismatch is visible. Verify ~/keap/src is at the tag first.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
SRC = pathlib.Path.home() / "keap/src/shared/contracts"
DST = REPO / "files/anatomy/face/src/lib/keap-contracts"
DEFAULTS = REPO / "roles/pazny.keap/defaults/main.yml"
FILES = ("visibility.ts", "table.ts", "field-concepts.ts")

HEADER = """/**
 * VENDORED from thisisait/nos-keap at {pin} — DO NOT EDIT. A pinned snapshot of
 * KEAP's DataTable schema: the authority the schema-pin gate (schema-pin.test.ts)
 * validates every state/keap-tables/*.table.yml against, so "a definition runs
 * ahead of the pin" is structurally impossible rather than release discipline
 * (cross-repo-contracts clause 2; the caddy-sessions incident is what it stops).
 *
 * Re-vendor ONLY on a keap_repo_ref bump: `tools/vendor-keap-contracts.py`.
 * A hand-edit here forks the contract — the exact drift the gate catches.
 * Upstream: nos-keap shared/contracts/{name}
 */
"""


def pin() -> str:
    m = re.search(r'^keap_repo_ref:\s*"?([^"\s]+)"?', DEFAULTS.read_text(), re.M)
    return m.group(1) if m else "UNKNOWN"


def rendered(name: str, p: str) -> str:
    return HEADER.format(pin=p, name=name) + (SRC / name).read_text(encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="fail if a vendored copy is stale")
    args = ap.parse_args()

    if not SRC.is_dir():
        print(f"vendor-keap-contracts: no KEAP clone at {SRC}", file=sys.stderr)
        return 2

    p = pin()
    print(f"keap_repo_ref = {p}  (from {DEFAULTS.name})")
    DST.mkdir(parents=True, exist_ok=True)
    stale = []
    for name in FILES:
        want = rendered(name, p)
        dst = DST / name
        if args.check:
            if not dst.is_file() or dst.read_text(encoding="utf-8") != want:
                stale.append(name)
        else:
            dst.write_text(want, encoding="utf-8")
            print(f"  vendored {name}")
    if args.check and stale:
        print(f"STALE: {', '.join(stale)} — run tools/vendor-keap-contracts.py", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
