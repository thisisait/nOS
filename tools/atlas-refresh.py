#!/usr/bin/env python3
"""Refresh the deployed nos-atlas data (Pulse geolibre:atlas-refresh).

Rebuilds the KEAP taxonomy fixture, then runs the nos-atlas README "nOS job contract"
(nos-atlas-data/1); every step is an argv list run from the nos-atlas checkout:

  0. node scripts/build-fixture.ts <keap-src>   (reads KEAP; writes fixtures/ in the atlas checkout)
  1. node scripts/snapshot-from-readers.mjs --out <tmp> --nos <this repo>   (read-only)
  2. node src/generator/build.ts --fixture <atlas>/fixtures/keap-taxonomy.json
       --snapshot <tmp> --nos <this repo> --out <data-dir>/plugins/nos-atlas/live

The plugin reads live/meta.json and falls back to its bundled data/ otherwise. The
generator writes in place, meta.json last; on bad input it writes nothing (exit 3).

  tools/atlas-refresh.py --data-dir <geolibre_data_dir> --atlas-src <nos_atlas_src_dir>
                         --keap-src <keap_src_dir>

Exit 0 done or off (empty --data-dir), 2 a missing KEAP checkout or node, otherwise the
failing step's exit code.
"""
from __future__ import annotations

import argparse
import pathlib
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
NODES = ("/opt/homebrew/bin/node", "/usr/local/bin/node", "/usr/bin/node")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-dir", required=True, help="geolibre_data_dir; empty = GeoLibre off")
    ap.add_argument("--atlas-src", required=True, help="the nos-atlas checkout (nos_atlas_src_dir)")
    ap.add_argument("--keap-src", required=True, help="the KEAP checkout (keap_src_dir), read only")
    a = ap.parse_args(argv)
    if not a.data_dir or not a.atlas_src:
        print("geolibre is off (no data dir): nothing to do")
        return 0
    src, keap = pathlib.Path(a.atlas_src), pathlib.Path(a.keap_src)
    fixture = src / "fixtures/keap-taxonomy.json"
    if not a.keap_src or not (keap / "knowledge/spine/manifest.json").is_file():
        print(f"KEAP checkout missing at {keap!s} (no knowledge/spine/manifest.json): the taxonomy "
              "fixture cannot be rebuilt, so nothing is drawn; the served set stays as it was",
              file=sys.stderr)
        return 2
    node = shutil.which("node") or next((n for n in NODES if pathlib.Path(n).is_file()), None)
    if not node:
        print("cannot build: no node binary", file=sys.stderr)
        return 2
    live = pathlib.Path(a.data_dir) / "plugins/nos-atlas/live"
    with tempfile.TemporaryDirectory(prefix="atlas-snapshot-") as snap:
        steps = (
            [node, "scripts/build-fixture.ts", str(keap)],
            [node, "scripts/snapshot-from-readers.mjs", "--out", snap, "--nos", str(REPO)],
            [node, "src/generator/build.ts", "--fixture", str(fixture), "--snapshot", snap,
             "--nos", str(REPO), "--out", str(live)],
        )
        for argv_ in steps:
            step = subprocess.run(argv_, cwd=src, capture_output=True, text=True, timeout=280, check=False)
            print(step.stdout.strip())
            if step.returncode != 0:
                print(f"{argv_[1]} exit {step.returncode}: {step.stderr.strip()[-2000:]}", file=sys.stderr)
                return step.returncode
    print(f"atlas data → {live}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
