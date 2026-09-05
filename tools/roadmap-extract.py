#!/usr/bin/env python3
"""One-time: live roadmap table -> per-row `<slug>.md` files in the PRIVATE seed repo.

The migration step for dtt-seed-per-row-file. Reads every row from the live KEAP
roadmap table and writes one markdown+frontmatter file per row into the seed dir
(NOS_SEED_DIR, default ~/nos-seed) — which must be your PRIVATE repo, because the
row bodies are your ideas and nOS is public.

    NOS_SEED_DIR=~/projects/nos-seed tools/roadmap-extract.py            # dry run
    NOS_SEED_DIR=~/projects/nos-seed tools/roadmap-extract.py --write    # write files

Run it once to seed the private repo from what the table already holds; after
that the files are the source and tools/roadmap-seed.py reads them. The extractor
reads the LIVE TABLE, never tools/roadmap-seed.py — the monolith's inline bodies
are being deleted, so the table (and git history) are the only remaining source,
and the table is authoritative.
"""

from __future__ import annotations

import datetime
import os
import sys

import urllib.request

from keap_api import human_headers
from roadmap_seed_lib import GIT_OWNED, SHIPPED, seed_dir  # noqa: F401

TABLE = "2d498264-bc9a-4324-9935-489e5e4d92f3"
BASE = f"http://127.0.0.1:8091/api/tables/{TABLE}"

# Frontmatter key order — readable files, stable diffs.
_FM_ORDER = ["slug", "title", "parent", "track", "task_type", "status", "when", "refs", "release"]


def _get_rows() -> list[dict]:
    req = urllib.request.Request(BASE + "/rows?limit=500", headers=human_headers())
    with urllib.request.urlopen(req) as r:
        return __import__("json").loads(r.read())["data"]["rows"]


def _when(v: dict) -> str:
    ts = v.get("occurred_at") or v.get("target")
    if not ts:
        return ""
    return datetime.datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d")


def _yaml_val(s: str) -> str:
    s = str(s or "")
    # Quote when YAML would otherwise mis-parse (colons, leading specials).
    if s == "" or any(c in s for c in ":#") or s[:1] in "!&*[]{}>|@`\"'%-? ":
        return '"' + s.replace('"', '\\"') + '"'
    return s


def _render(v: dict) -> str:
    fm = {
        "slug": v.get("slug", ""),
        "title": v.get("title", ""),
        "parent": v.get("parent", ""),
        "track": v.get("track", ""),
        "task_type": v.get("task_type", ""),
        "status": v.get("status", ""),
        "when": _when(v),
        "refs": v.get("refs", ""),
        "release": v.get("release", ""),
    }
    lines = ["---"]
    for k in _FM_ORDER:
        lines.append(f"{k}: {_yaml_val(fm[k])}")
    lines.append("---")
    lines.append("")
    lines.append((v.get("body") or "").strip())
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    write = "--write" in sys.argv
    d = seed_dir()
    if not any(a.startswith("NOS_SEED_DIR") for a in os.environ) and "NOS_SEED_DIR" not in os.environ:
        print(f"note: NOS_SEED_DIR unset — using default {d}", file=sys.stderr)
    rows = _get_rows()
    print(f"live table: {len(rows)} rows -> {d}" + ("" if write else "  (DRY RUN, pass --write)"))
    if write:
        os.makedirs(d, exist_ok=True)
    written = 0
    for r in rows:
        v = r["values"]
        slug = v.get("slug")
        if not slug:
            print(f"  SKIP a row with no slug (id {r.get('id')})", file=sys.stderr)
            continue
        path = os.path.join(d, f"{slug}.md")
        if write:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(_render(v))
        else:
            print(f"  [dry] {slug}.md")
        written += 1
    if write:
        print(f"wrote {written} files. Commit them in your PRIVATE seed repo — "
              f"never in nOS.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
