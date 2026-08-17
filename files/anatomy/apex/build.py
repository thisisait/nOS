#!/usr/bin/env python3
"""Build the public apex site: artifact -> gate -> projection -> pages.

    python3 files/anatomy/apex/build.py            # writes dist/
    open files/anatomy/apex/dist/index.html        # the operator's preview

The build refuses to run (exit 2) if the ruling file does not cover the
artifact — see projection.GateError — and refuses to write (exit 3) if
any withheld term would reach the output — see projection.LeakError.
The leak check runs over EVERY text file emitted, not just the JSON.

dist/ is gitignored and route-less on purpose: nothing serves it until
the operator signs the ruling and a separate, deliberate change wires
the edge.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import projection  # noqa: E402
import render  # noqa: E402

APEX = Path(__file__).resolve().parent
DIST = APEX / "dist"
ASSETS = APEX / "assets"


def build(out_dir: Path = DIST) -> Path:
    artifact = projection.load_artifact()
    ruling = projection.load_ruling()

    # projection (gates inside), then render — both from the public doc only
    doc_text = projection.public_json(artifact, ruling)
    doc = __import__("json").loads(doc_text)
    seed = f"{ruling['ruling']}:{ruling['version']}"   # build-time constant (D3)
    html = render.page_html(doc, seed)
    css = (ASSETS / "ait.css").read_text(encoding="utf-8")

    # every emitted text surface passes the leak check
    for name, text in (("index.html", html), ("public-anatomy.json", doc_text),
                       ("ait.css", css)):
        try:
            projection.leak_check(text, artifact, ruling)
        except projection.LeakError as exc:
            print(f"REFUSED: {name}: {exc}", file=sys.stderr)
            sys.exit(3)

    if out_dir.exists():
        shutil.rmtree(out_dir)
    (out_dir / "assets").mkdir(parents=True)
    (out_dir / "index.html").write_text(html, encoding="utf-8")
    (out_dir / "public-anatomy.json").write_text(doc_text, encoding="utf-8")
    (out_dir / "assets" / "ait.css").write_text(css, encoding="utf-8")
    shutil.copytree(ASSETS / "fonts", out_dir / "assets" / "fonts")
    return out_dir


if __name__ == "__main__":
    try:
        out = build()
    except projection.GateError as exc:
        print(f"BUILD HALTED BY THE RULING GATE:\n{exc}", file=sys.stderr)
        sys.exit(2)
    print(f"built: {out}/index.html")
    print("preview: open " + str(out / "index.html"))
    print("NOT wired to any route; ruling status governs deployability.")
