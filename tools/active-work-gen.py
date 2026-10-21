#!/usr/bin/env python3
"""Project the roadmap seed into docs/active-work.md (row active-work-from-table).

Everything above MARKER in the file is hand-written and kept verbatim, including
the `Current release row:` line that names the release. Below it: Now = that
release row, rows with release/parent on it and their children, status active|next;
Open follow-ups = every blocked|parked row. Seed unreachable: UNKNOWN, rc 3, no write.
"""
from __future__ import annotations

import argparse
import difflib
import os
import pathlib
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import roadmap_seed_lib as lib  # noqa: E402

OUT = pathlib.Path(__file__).resolve().parents[1] / "docs" / "active-work.md"
MARKER = ("<!-- Below this line: projected from the roadmap seed by tools/active-work-gen.py."
          " Edit the rows, then rerun it; never edit below by hand. -->")
RELEASE = re.compile(r"Current release row: `([A-Za-z0-9_-]+)`")
NOW, FOLLOW = ("active", "next"), ("blocked", "parked")


def _line(r: dict) -> str:
    # Slug + status only: titles/bodies are the private ideas (roadmap_seed_lib INDEX_PATH);
    # `nos dtt status` or the seed file holds the words.
    return f"- `{r['slug']}` **{r.get('status', '')}**"


def _sorted(rows):
    return sorted(rows, key=lambda r: (lib.rank(r.get("status")), r["slug"]))


def render(header: str, rows: list[dict]) -> str:
    m = RELEASE.search(header)
    if not m:
        raise SystemExit("header has no `Current release row: `<slug>`` line")
    rel = m.group(1)
    tree = {rel} | {r["slug"] for r in rows if rel in (r["release"], r["parent"])}
    while True:  # children of children
        more = {r["slug"] for r in rows if r["parent"] in tree} - tree
        if not more:
            break
        tree |= more
    now = [r for r in rows if r["slug"] in tree and r.get("status") in NOW]
    follow = [r for r in rows if r.get("status") in FOLLOW]
    parts = [header.rstrip("\n"), "", MARKER, "",
             f"## Now — `{rel}` and its rows ({', '.join(NOW)})", ""]
    parts += [_line(r) for r in _sorted(now)] or ["- (none)"]
    parts += ["", f"## Open follow-ups ({', '.join(FOLLOW)})", ""]
    parts += [_line(r) for r in _sorted(follow)] or ["- (none)"]
    return "\n".join(parts) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if the file is not current")
    a = ap.parse_args()
    try:
        rows = lib.load_rows()
    except (OSError, ValueError) as e:
        print(f"UNKNOWN: roadmap seed unreadable ({lib.seed_dir()}): {str(e).splitlines()[0]}")
        return 3
    have = OUT.read_text(encoding="utf-8")
    want = render(have.split(MARKER, 1)[0], rows)
    if a.check:
        if have == want:
            return 0
        sys.stdout.writelines(difflib.unified_diff(
            have.splitlines(True), want.splitlines(True), "committed", "projected"))
        return 1
    OUT.write_text(want, encoding="utf-8")
    print(f"wrote {OUT.relative_to(OUT.parents[1])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
