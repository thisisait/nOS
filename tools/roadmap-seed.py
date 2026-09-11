#!/usr/bin/env python3
"""Seed / --sync the nOS Roadmap table from per-row files in the PRIVATE seed repo.

WAS a 2286-line monolith that inlined every row's prose — which broke twice under
hand-editing (2026-09-04) AND published every idea into the PUBLIC nOS repo. Now
it is a READER OF FILES (dtt-seed-per-row-file, docs/plans/datatables-subsystem.md
§6): one row = one `<slug>.md` in a SEPARATE PRIVATE repo (NOS_SEED_DIR, default
~/nos-seed), readable and atomic for parallel agents. This file carries the
machinery; the row content lives in the operator's private repo and never here.

First-time setup: `tools/roadmap-extract.py --write` writes the live table into
NOS_SEED_DIR; commit those in your private repo. Thereafter the files are the
source of the git-owned half (title/parent/track/refs/body); the table owns
status/target/occurred_at/verified* (moved by roadmap-update.py / -verify.py).

Usage:  python3 tools/roadmap-seed.py [--dry-run] [--sync]
  (no flag)  insert rows whose slug is not in the table yet; skip existing.
  --sync     also reconcile the git-owned half of rows that already exist.
  --dry-run  print what would change; write nothing.

The two columns target/occurred_at: exactly one is set per row, decided by
status — a null date is indistinguishable from one nobody wrote. The live table
predates state/keap-tables/roadmap.table.yml; this preflights the schema and
refuses (naming the missing columns) rather than POSTing an unknown key.
"""

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

from keap_api import human_base, human_headers, write_row  # noqa: E402 — sibling helper in tools/
from roadmap_seed_lib import GIT_OWNED, load_rows, seed_dir, write_index  # noqa: E402

_REPO = __import__("os").path.abspath(__import__("os").path.join(
    __import__("os").path.dirname(__file__), ".."))
#: NOS_ROADMAP_TABLE_ID overrides for an estate whose roadmap table was minted
#: through the agent door (id == slug, e.g. "roadmap"); KEAP_API_URL for a
#: non-default loopback publish. Defaults are the operator estate's values.
TABLE = os.environ.get("NOS_ROADMAP_TABLE_ID", "2d498264-bc9a-4324-9935-489e5e4d92f3")
BASE = f"{human_base()}/api/tables/{TABLE}"
H = human_headers()  # identity + SEC-02 x-keap-proxy-secret (else /api 401s)


def req(m, u, b=None):
    r = urllib.request.Request(
        u, data=json.dumps(b).encode() if b else None, headers=H, method=m)
    with urllib.request.urlopen(r) as x:
        return json.loads(x.read())


# ── The rows, read from the private seed repo (not inlined here) ─────────────
R = load_rows(seed_dir())

# ── Structural checks on the prepared rows (against each other) ──────────────
slugs = {r["slug"] for r in R}
orphans = [(r["slug"], r["parent"]) for r in R if r["parent"] and r["parent"] not in slugs]
if orphans:
    sys.exit(f"REFUSING: parent slugs that resolve to nothing: {orphans}")
dupes = [s for s in slugs if sum(1 for r in R if r["slug"] == s) > 1]
if dupes:
    sys.exit(f"REFUSING: duplicate slugs: {dupes}")
print(f"loaded {len(R)} rows from {seed_dir()} · orphan check: OK · duplicate check: OK")

DRY_RUN = "--dry-run" in sys.argv
SYNC = "--sync" in sys.argv

# Keep the PUBLIC structural index current from the private files (the offline
# gates read it). Derived from the files, not the table, so it is written on a
# real run regardless of what the table does; a dry run touches nothing.
if not DRY_RUN:
    # The public index belongs to the ESTATE roadmap in the nOS checkout; a
    # personal/project table (dtt-per-user-tables) has no public half, and a
    # non-maintainer cannot write the checkout anyway.
    if TABLE in ("roadmap", "2d498264-bc9a-4324-9935-489e5e4d92f3") and os.access(
            os.path.join(_REPO, "state", "roadmap"), os.W_OK):
        print(f"index: wrote {write_index(R, _REPO)}")
    else:
        print("index: skipped (not the estate roadmap, or the checkout is read-only for you)")

# ── Preflight: does the live table carry the columns this writes? ───────────
# The live table was created before state/keap-tables/roadmap.table.yml and
# nothing applies that definition, so a column may simply not be there — and a
# POST with an unknown key fails in a way easy to write and hard to read. Refuse
# BEFORE writing, name the missing columns, exit non-zero. Runs under --dry-run
# too: a rehearsal that skips the check rehearses the wrong run.
_live_schema = req("GET", BASE)["data"].get("schema", {}).get("columns") or []
_live_cols = {c.get("key") for c in _live_schema}
_live_kinds = {c.get("key"): c.get("kind") for c in _live_schema}


# `refs` is a `·`-separated string in the seed file (the readable form) but
# state/keap-tables/roadmap.table.yml declares the column `kind: json`. The
# operator estate's table predates that definition and holds refs as text,
# so the mismatch surfaced only on the first estate whose table WAS created
# from the definition (the DGX, 2026-09-07: `invalid row: refs: expected
# object/array`). The live kind decides the wire shape; the file keeps its form.
def _refs_wire(value):
    if _live_kinds.get("refs") != "json" or not isinstance(value, str):
        return value
    return [s.strip() for s in value.split("\u00b7") if s.strip()]


def _refs_file(value):
    """The inverse, for comparing a live row against its file."""
    if isinstance(value, list):
        return " \u00b7 ".join(str(v) for v in value)
    return value or ""
_need = {k for r in R for k in r}
_missing = sorted(_need - _live_cols)
if _live_cols and _missing:
    sys.exit(
        "REFUSING: the live table is missing column(s) this script writes: "
        + ", ".join(_missing)
        + "\n  Apply state/keap-tables/roadmap.table.yml (or add the columns in"
          "\n  the Planner) before seeding — do not widen this script to fit a"
          "\n  schema the definition has already moved past."
        + f"\n  live columns: {' '.join(sorted(_live_cols))}")
if not _live_cols:
    sys.exit("REFUSING: could not read the live table's schema — cannot tell "
             "whether a write would land. Is KEAP up?")

# ── The half git owns (files) vs the half the table owns (roadmap-update) ────
# git owns   slug title parent track refs body   — authored in the files
# table owns status target occurred_at verified* — moved by roadmap-update.py
# --sync reconciles the git-owned half for existing rows; without it this is
# purely additive.
live_rows = {r["values"].get("slug"): r
             for r in req("GET", BASE + "/rows?limit=500")["data"]["rows"]}
existing = set(live_rows)
fresh = [r for r in R if r["slug"] not in existing]
skipped = len(R) - len(fresh)

drifted = []
if SYNC:
    for r in R:
        cur = live_rows.get(r["slug"])
        if cur is None:
            continue
        delta = {k: r[k] for k in GIT_OWNED
                 if k in r and r[k] != (_refs_file(cur["values"].get(k)) if k == "refs"
                                        else (cur["values"].get(k) or ""))}
        if delta:
            drifted.append((r, delta, cur["id"]))

print(f"already present: {skipped} · to insert: {len(fresh)}"
      + (f" · git-owned drift on {len(drifted)}" if SYNC else ""))

if DRY_RUN:
    for r in fresh:
        print(f"  [dry] would insert {r['slug']:<24} {r['title'][:60]}")
    for r, delta, _ in drifted:
        print(f"  [dry] would sync   {r['slug']:<24} {', '.join(sorted(delta))}")
    print(f"DRY RUN — nothing written. {len(fresh)} insert(s), {len(drifted)} sync(s).")
    sys.exit(0)

# ── BOTH WRITES GO THROUGH THE AGENT DOOR, AND THE DOOR IS NOT A DETAIL. ─────
# The human API mints a UUID and has no update; the agent API's upsert keys on
# the ID (= slug here). A row inserted through the human door can never be
# changed afterwards — an "update" matches nothing and inserts a duplicate.
# tools/keap-reid-rows.py exists to repair rows created the wrong way.
_agent_tok = None


def _agent_token():
    global _agent_tok
    if _agent_tok is None:
        import os
        _agent_tok = os.environ.get("KEAP_AGENT_TOKEN_RW", "").strip() or subprocess.run(
            ["docker", "exec", "iiab-keap-1", "printenv", "KEAP_AGENT_TOKEN_RW"],
            capture_output=True, text=True).stdout.strip()
        if not _agent_tok:
            sys.exit("REFUSING: no KEAP_AGENT_TOKEN_RW. The human API has no row "
                     "update at all, and its inserts mint ids no later write can "
                     "reach — so neither half of this run may use it.")
    return _agent_tok


AGENT = f"http://127.0.0.1:8091/agent/v1/tables/{TABLE}/rows"


def agent_write(values):
    if "refs" in values:
        values = {**values, "refs": _refs_wire(values["refs"])}
    # One helper decides the door: the identity outpost (as the caller, human
    # door, owner/tier/grants apply) or the agent door with the RW bearer.
    try:
        return write_row(TABLE, values)
    except RuntimeError as e:
        sys.exit(f"REFUSING: writing {values.get('slug')} failed — {e}")


# Insert what we can. A row the live table rejects (e.g. an unknown `track`
# select-option) must not abort the batch and bury its one-line reason under a
# urllib traceback — collect the slug + the server's own message and report
# them together at the end, having still landed every valid row.
failures = []
for r in fresh:
    try:
        agent_write(r)
    except urllib.error.HTTPError as e:
        failures.append((r["slug"], e.read().decode("utf-8", "replace").strip()))

if drifted:
    unkeyed = [r["slug"] for r, _, rid in drifted if rid != r["slug"]]
    if unkeyed:
        sys.exit("REFUSING: these rows are not addressed by their slug, so a "
                 f"sync would duplicate them: {', '.join(unkeyed)}\n"
                 "  run `tools/keap-reid-rows.py --apply` first.")
    for r, delta, _ in drifted:
        try:
            agent_write({"slug": r["slug"], "title": r["title"],
                         "status": live_rows[r["slug"]]["values"].get("status"), **delta})
            print(f"  synced {r['slug']:<24} {', '.join(sorted(delta))}")
        except urllib.error.HTTPError as e:
            failures.append((r["slug"], e.read().decode("utf-8", "replace").strip()))

after = req("GET", BASE + "/rows?limit=500")["data"]["rows"]
tops = [x for x in after if not x["values"].get("parent")]
print(f"seeded: {len(after)} rows | top-level {len(tops)} | nested {len(after)-len(tops)}")

if failures:
    print(f"\n{len(failures)} row(s) the live table REJECTED (valid rows above still landed):")
    for slug, body in failures:
        print(f"  ✗ {slug:<26} {body[:160]}")
    sys.exit(1)
