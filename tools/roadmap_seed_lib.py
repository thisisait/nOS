"""Per-row seed files → row dicts. The public machinery; the CONTENT is private.

dtt-seed-per-row-file (docs/plans/datatables-subsystem.md §6): a roadmap row is
one markdown+frontmatter file — readable, diffable, and atomic for parallel
agents (two agents editing two rows touch two files). The old
tools/roadmap-seed.py was a 2286-line monolith that inlined every row's prose,
which (a) broke twice under hand-editing and (b) published every idea into the
PUBLIC nOS repo.

So the files live in a SEPARATE PRIVATE REPO, not here. This module only knows
how to FIND that repo and PARSE its files — it carries no row content. The
public nOS repo ships the parser, the loader (roadmap-seed.py), the extractor
(roadmap-extract.py), and state/roadmap/_template.md; the operator's private
repo holds `<slug>.md` per row.

File format (state/roadmap/_template.md is the canonical example):

    ---
    slug: sec-p1
    title: P1 — HKDF derivation + per-user scope
    parent: sec
    track: security
    task_type: code-fix          # optional (dtt-task-types); "" if unset
    status: next                 # INSERT-time seed; the table owns it after
    when: 2026-08-03             # a date; STATUS decides target vs occurred_at
    refs: "docs/... · ..."
    release: ""
    ---
    <body prose — the measurement, the defect, the fix, the gate>

git owns title/parent/track/refs/task_type/body (authored in the file, synced by
--sync); the table owns status/target/occurred_at/verified* (moved by
roadmap-update.py / roadmap-verify.py). status+when in a file seed a FRESH row's
insert only; --sync never overwrites the table-owned half.
"""

from __future__ import annotations

import datetime
import os

import yaml

SHIPPED = "shipped"

#: git-owned columns — the half a file authors and --sync reconciles.
#: task_type is authored in the frontmatter (dtt-task-types) but is NOT here yet:
#: the live roadmap table has no task_type column, and the seeder's preflight
#: refuses to write a column that does not exist. When roadmap.table.yml gains
#: task_type and it is applied, add it here and to the emitted row dict.
GIT_OWNED = ("title", "parent", "track", "refs", "body")


def seed_dir() -> str:
    """Resolve the PRIVATE seed repo path. NOS_SEED_DIR wins; else the default.

    Never inside the public checkout — the whole point is that row content is
    not committed to nOS. Default is ~/nos-seed; override with NOS_SEED_DIR.
    """
    d = os.environ.get("NOS_SEED_DIR", "").strip()
    if not d:
        d = os.path.join(os.path.expanduser("~"), "nos-seed")
    return os.path.abspath(os.path.expanduser(d))


def _ts(d: str) -> int:
    return int(datetime.datetime.strptime(d, "%Y-%m-%d").timestamp())


def parse_file(path: str) -> dict:
    """One `<slug>.md` → the row dict shape roadmap-seed.py consumes.

    Exactly one date key is set (target OR occurred_at), decided by status —
    a null date column is indistinguishable from one nobody wrote, which is the
    whole reason the two columns exist (roadmap-seed.py's original note).
    """
    raw = open(path, encoding="utf-8").read()
    if not raw.startswith("---"):
        raise ValueError(f"{path}: no YAML frontmatter (must start with '---')")
    _, fm, body = raw.split("---", 2)
    meta = yaml.safe_load(fm) or {}
    slug = str(meta.get("slug") or "").strip()
    if not slug:
        raise ValueError(f"{path}: frontmatter has no slug")
    status = str(meta.get("status") or "").strip()
    when = str(meta.get("when") or "").strip()
    if not status or not when:
        raise ValueError(f"{path}: both status and when are required")
    at = _ts(when)
    # task_type is parsed for validation but NOT emitted into the seed payload
    # yet — the roadmap table has no such column (see GIT_OWNED note). It stays
    # authored in the file, ready for when the column is added.
    row = dict(
        slug=slug,
        title=str(meta.get("title") or "").strip(),
        parent=str(meta.get("parent") or "").strip(),
        status=status,
        track=str(meta.get("track") or "").strip(),
        release=str(meta.get("release") or "").strip(),
        refs=str(meta.get("refs") or "").strip(),
        body=body.strip(),
        **({"occurred_at": at} if status == SHIPPED else {"target": at}),
    )
    return row


#: Keys the seeder emits into a row payload (a PUBLIC code contract — the gate
#: test_the_roadmap_declares_the_table_it_fills reads this instead of parsing
#: row() out of the seeder, which no longer inlines rows). target/occurred_at is
#: the status-decided date column; one or the other is always present.
WRITTEN_KEYS = ("slug", "title", "parent", "status", "track", "release", "refs",
                "body", "target", "occurred_at")

#: The PUBLIC, content-free index (slug graph only — no titles/bodies/refs, which
#: are the private ideas). Slugs are already public (state/roadmap-probes.yml,
#: face `implements:` bindings), so this leaks nothing new; it lets offline gates
#: validate that a slug/status is real without reading the private seed repo.
INDEX_PATH = "state/roadmap/index.yml"
_INDEX_FIELDS = ("slug", "parent", "track", "status")


def write_index(rows: list[dict], repo_root: str) -> str:
    """Write the structural slug index (public) from loaded rows. Returns its path."""
    idx = sorted(
        ({k: (r.get(k) or "") for k in _INDEX_FIELDS} for r in rows),
        key=lambda r: r["slug"],
    )
    path = os.path.join(repo_root, INDEX_PATH)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    header = (
        "# GENERATED — the PUBLIC, content-free roadmap slug index.\n"
        "# slug graph + status only; NO titles/bodies/refs (those are the private\n"
        "# ideas, in NOS_SEED_DIR). Regenerated by tools/roadmap-seed.py from the\n"
        "# private seed files; offline gates read it to check a slug/status is real.\n"
        "# status is a snapshot (the table owns it); the slug graph is the stable part.\n"
    )
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(header)
        yaml.safe_dump(idx, fh, sort_keys=False, allow_unicode=True, width=200)
    return path


def load_rows(directory: str | None = None) -> list[dict]:
    """Every `<slug>.md` under the seed dir (skips `_`-prefixed like _template)."""
    d = directory or seed_dir()
    if not os.path.isdir(d):
        raise FileNotFoundError(
            f"seed dir not found: {d}\n"
            "  The roadmap row files live in a PRIVATE repo, not in nOS. Clone it "
            "there (or set NOS_SEED_DIR), or run tools/roadmap-extract.py to "
            "populate it from the live table the first time.")
    rows = []
    for name in sorted(os.listdir(d)):
        if name.endswith(".md") and not name.startswith("_"):
            rows.append(parse_file(os.path.join(d, name)))
    return rows


if __name__ == "__main__":
    import json
    import sys
    rows = load_rows(sys.argv[1] if len(sys.argv) > 1 else None)
    print(f"{len(rows)} rows from {sys.argv[1] if len(sys.argv) > 1 else seed_dir()}")
    if "--dump" in sys.argv:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
