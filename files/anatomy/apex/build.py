#!/usr/bin/env python3
"""Build the public apex site: artifact -> gate -> projection -> pages.

    python3 files/anatomy/apex/build.py            # writes dist/ (PREVIEW)
    open files/anatomy/apex/dist/index.html        # the operator's preview

    # the converge path (roles/pazny.apex) — refuses an unsigned ruling:
    python3 files/anatomy/apex/build.py --require-signed --out <web root>

The build refuses to run (exit 2) if the ruling file does not cover the
artifact — see projection.GateError — and refuses to write (exit 3) if
any withheld term would reach the output — see projection.LeakError.
The leak check runs over EVERY text file emitted, not just the JSON.

--require-signed adds the DEPLOY gate (exit 4): the ruling must carry
``status: SIGNED`` and a non-empty ``signed_by`` (projection.serve_gate).
Without the flag, dist/ is a local preview: gitignored and route-less on
purpose — nothing serves it until the operator signs the ruling and the
pazny.apex role (which always passes --require-signed) converges it into
the web root. There is no flag to point this at a different ruling file:
the gate reads the committed ruling or nothing.
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

    # EVERY emitted text surface passes the leak check — which until
    # 2026-08-17 meant the three generated ones only, while the copied font
    # licences went out unread. They are prose that a person edits, they sit
    # at a guessable public path, and the day one of them named an internal
    # service nothing would have said so. Copied text is now checked with
    # the rest, BEFORE anything is written.
    copied = [(p.name, p.read_text(encoding="utf-8"))
              for p in sorted((ASSETS / "fonts").glob("*"))
              if p.is_file() and p.suffix in {".txt", ".md"}]
    for name, text in [("index.html", html), ("public-anatomy.json", doc_text),
                       ("ait.css", css), *copied]:
        try:
            projection.leak_check(text, artifact, ruling)
        except projection.LeakError as exc:
            print(f"REFUSED: {name}: {exc}", file=sys.stderr)
            sys.exit(3)

    if out_dir.exists():
        # Refuse to erase a directory that is not a previous apex build —
        # a mistyped --out must fail, not empty someone's directory.
        existing = {p.name for p in out_dir.iterdir()}
        if existing and not {"index.html", "public-anatomy.json"} & existing:
            raise projection.GateError(
                f"--out {out_dir} exists and does not look like a previous "
                "apex build; refusing to erase it"
            )
        # CLEAR THE CONTENTS, NEVER THE DIRECTORY. Measured 2026-08-17, on the
        # first rebuild after the site went live: rmtree + mkdir gives the web
        # root a NEW inode, and the running container's bind mount still points
        # at the old one. The host directory looked perfect, the converge
        # reported failed=0, and https://pazny.eu answered 403 to the world
        # because nginx was looking at a directory that no longer had a name.
        # Only the smoke probe said so. Keeping the inode keeps the mount.
        for child in out_dir.iterdir():
            shutil.rmtree(child) if child.is_dir() else child.unlink()
    (out_dir / "assets").mkdir(parents=True, exist_ok=True)
    (out_dir / "index.html").write_text(html, encoding="utf-8")
    (out_dir / "public-anatomy.json").write_text(doc_text, encoding="utf-8")
    (out_dir / "assets" / "ait.css").write_text(css, encoding="utf-8")
    # `upstream/` holds the full unsubsetted binaries the vendored subsets are
    # cut from. They are provenance, not payload: copying them would put the
    # 1.9 MB this page was trimmed of back inside the web root, reachable by
    # anyone who guesses the path.
    shutil.copytree(ASSETS / "fonts", out_dir / "assets" / "fonts",
                    ignore=shutil.ignore_patterns("upstream"))
    return out_dir


def main(argv: list[str]) -> int:
    require_signed = False
    out_dir = DIST
    args = list(argv)
    while args:
        arg = args.pop(0)
        if arg == "--require-signed":
            require_signed = True
        elif arg == "--out":
            if not args:
                print("--out needs a directory", file=sys.stderr)
                return 2
            out_dir = Path(args.pop(0)).expanduser()
        else:
            print(f"unknown argument: {arg!r}", file=sys.stderr)
            return 2

    try:
        if require_signed:
            projection.serve_gate(projection.load_ruling())
    except projection.GateError as exc:
        print(f"SERVING REFUSED — THE RULING IS NOT SIGNED:\n{exc}", file=sys.stderr)
        return 4

    try:
        out = build(out_dir)
    except projection.GateError as exc:
        print(f"BUILD HALTED BY THE RULING GATE:\n{exc}", file=sys.stderr)
        return 2
    print(f"built: {out}/index.html")
    if require_signed:
        print("ruling is SIGNED; output may be served.")
    else:
        print("preview: open " + str(out / "index.html"))
        print("NOT wired to any route; ruling status governs deployability.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
