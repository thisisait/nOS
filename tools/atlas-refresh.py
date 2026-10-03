#!/usr/bin/env python3
"""Refresh the deployed nos-atlas data (Pulse geolibre:atlas-refresh).

Runs the nos-atlas README "nOS job contract" (nos-atlas-data/1), both steps with argv
lists from the nos-atlas checkout:

  1. node scripts/snapshot-from-readers.mjs --out <tmp> --nos <this repo>   (read-only)
  2. node src/generator/build.ts --fixture <atlas>/fixtures/keap-taxonomy.json
       --snapshot <tmp> --nos <this repo> --out <data-dir>/plugins/nos-atlas/live

The plugin reads live/meta.json and falls back to its bundled data/ otherwise. The
generator writes in place, meta.json last; on bad input it writes nothing (exit 3).
The KEAP taxonomy fixture is not rebuilt here (build-fixture.ts writes into the checkout).

  tools/atlas-refresh.py --data-dir <geolibre_data_dir> --atlas-src <nos_atlas_src_dir>

Exit 0 done or off (empty --data-dir), otherwise the failing step's exit code.
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
    a = ap.parse_args(argv)
    if not a.data_dir or not a.atlas_src:
        print("geolibre is off (no data dir): nothing to do")
        return 0
    src = pathlib.Path(a.atlas_src)
    fixture = src / "fixtures/keap-taxonomy.json"
    node = shutil.which("node") or next((n for n in NODES if pathlib.Path(n).is_file()), None)
    if not fixture.is_file() or not node:
        print(f"cannot build: {fixture} present={fixture.is_file()}, node={node}", file=sys.stderr)
        return 2
    live = pathlib.Path(a.data_dir) / "plugins/nos-atlas/live"
    with tempfile.TemporaryDirectory(prefix="atlas-snapshot-") as snap:
        steps = (
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
