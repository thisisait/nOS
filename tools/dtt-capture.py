#!/usr/bin/env python3
"""Capture an idea / plan / spec into dtt as a per-row seed file (dtt-capture).

The machinery behind the `dtt-capture` skill and the operator directive "define
plans/specs ONLY via a skill + dtt" (memory track-via-skill-and-dtt). It writes
ONE `<slug>.md` into the PRIVATE seed repo (NOS_SEED_DIR) in the canonical
per-row format, so the idea is tracked in the roadmap DataTable on the next
`tools/roadmap-seed.py` run — never a hand-authored docs/plans/*.md again.

It writes THROUGH the machinery, not around it: same format
(roadmap_seed_lib.render_row_file), same validation the loader applies, and it
refuses a bad slug (KEAP assertRowId), an unknown task_type, or an unknown
status BEFORE writing — a file that would fail the seeder is not written.

    tools/dtt-capture.py --slug my-idea --title "One line" --track platform \
        --task-type design --status next --parent dtt --body "the prose"
    echo "the prose" | tools/dtt-capture.py --slug my-idea --title "..." --track platform
    tools/dtt-capture.py --slug existing --title "..." --track platform --update

Status/verified stay TABLE-owned after insert (moved by roadmap-update.py /
roadmap-verify.py); the file's status seeds the row and title/parent/track/refs/
body are the git-owned half. Commit the file in your PRIVATE seed repo — never
in nOS.
"""

from __future__ import annotations

import argparse
import os
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import roadmap_seed_lib as lib  # noqa: E402

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_TASK_TYPES = os.path.join(_REPO, "state", "task-types.yml")
_TABLE_DEF = os.path.join(_REPO, "state", "keap-tables", "roadmap.table.yml")


def _die(msg: str) -> None:
    sys.exit(f"REFUSING: {msg}")


def _known_task_types() -> set[str]:
    try:
        return set((yaml.safe_load(open(_TASK_TYPES, encoding="utf-8")) or {}).get("task_types", {}))
    except OSError:
        return set()


def _declared_statuses() -> set[str]:
    try:
        spec = yaml.safe_load(open(_TABLE_DEF, encoding="utf-8")) or {}
        cols = {c["key"]: c for c in spec.get("schema", {}).get("columns", [])}
        return set(cols.get("status", {}).get("options") or [])
    except OSError:
        return set()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--slug", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--track", required=True,
                    help="platform|security|agents|cortex|face|release|filesystem")
    ap.add_argument("--parent", default="")
    ap.add_argument("--task-type", default="", dest="task_type")
    ap.add_argument("--status", default="")
    ap.add_argument("--when", default="", help="YYYY-MM-DD")
    ap.add_argument("--refs", default="")
    ap.add_argument("--release", default="")
    ap.add_argument("--body", default=None, help="prose; if omitted, read from stdin")
    ap.add_argument("--body-file", default=None)
    ap.add_argument("--update", action="store_true", help="overwrite an existing file")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not lib.SLUG_RE.match(args.slug):
        _die(f"slug {args.slug!r} is not a valid row id — KEAP requires "
             r"[A-Za-z0-9_-]{1,128} (no spaces, dots, slashes).")
    if args.task_type:
        known = _known_task_types()
        if known and args.task_type not in known:
            _die(f"task_type {args.task_type!r} is not in state/task-types.yml.\n"
                 f"  known: {', '.join(sorted(known))}\n"
                 "  adding a type is a PROPOSAL through the loop, not an ad-hoc value.")
    if args.status:
        declared = _declared_statuses()
        if declared and args.status not in declared:
            _die(f"status {args.status!r} is not declared in roadmap.table.yml.\n"
                 f"  declared: {', '.join(sorted(declared))}")

    body = args.body
    if body is None and args.body_file:
        body = open(args.body_file, encoding="utf-8").read()
    if body is None:
        body = sys.stdin.read() if not sys.stdin.isatty() else ""

    fm = {
        "slug": args.slug, "title": args.title, "parent": args.parent,
        "track": args.track, "task_type": args.task_type, "status": args.status,
        "when": args.when, "refs": args.refs, "release": args.release,
    }
    rendered = lib.render_row_file(fm, body)

    # Self-check: the file we are about to write must PARSE as a seed row, or the
    # loader would choke on it later — catch it here, at authoring time.
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as tf:
        tf.write(rendered)
        _probe = tf.name
    try:
        lib.parse_file(_probe)
    except ValueError as exc:
        os.unlink(_probe)
        _die(f"the row this would write does not parse: {exc}")
    os.unlink(_probe)

    d = lib.seed_dir()
    path = os.path.join(d, f"{args.slug}.md")
    exists = os.path.exists(path)
    if exists and not args.update:
        _die(f"{path} already exists — pass --update to overwrite (an idea's "
             "STATUS is moved with roadmap-update.py, not by rewriting the file).")

    if args.dry_run:
        print(f"[dry] would {'update' if exists else 'create'} {path}\n")
        print(rendered)
        return 0

    os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(rendered)
    print(f"{'updated' if exists else 'wrote'} {path}")
    print("  → commit it in your PRIVATE seed repo, then `tools/roadmap-seed.py "
          "--dry-run` to see it land.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
