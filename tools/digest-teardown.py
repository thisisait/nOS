#!/usr/bin/env python3
"""digest-teardown — the inverse of seed-bundle.yml.

Delete a bundle's rows LEAF-FIRST (reverse dependency order, nos_digest.teardown_plan),
RETAINING any row another firm still references (the referrers probe = the
onDelete:restrict-safe check). One mechanism for two jobs the operator named:
a fast from-blank reset to tune the digest pipeline, and an agency removing a
client firm's data. Symmetric with the seeder: seed-bundle.yml grows a bundle in
dependency order, this tears the same bundle down in reverse.

DRY RUN BY DEFAULT (destructive-op doctrine — a delete is asked for in so many
words). --confirm deletes; each delete is still gated by the referrers probe, so
a shared party row survives even under --confirm.

  tools/digest-teardown.py state/fixtures/kolben-it.seed.yml            # plan + delete-safety, no writes
  tools/digest-teardown.py state/fixtures/kolben-it.seed.yml --confirm  # delete the unreferenced rows

Exit 0 done/dry · 1 a delete failed · 2 KEAP unreadable.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
import urllib.error
import urllib.request

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "files" / "anatomy" / "module_utils"))
from keap_api import human_headers, proxy_header  # noqa: E402
import nos_digest  # noqa: E402

API = "http://127.0.0.1:8091/api/tables"
AGENT = "http://127.0.0.1:8091/agent/v1/tables"


def _ro_token() -> str:
    tok = os.environ.get("KEAP_AGENT_TOKEN_RO", "").strip()
    if tok:
        return tok
    return subprocess.run(["docker", "exec", "iiab-keap-1", "printenv", "KEAP_AGENT_TOKEN_RO"],
                          capture_output=True, text=True).stdout.strip()


def _json(url: str, headers: dict, method: str = "GET"):
    req = urllib.request.Request(url, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=15) as r:
        body = r.read()
        return json.loads(body) if body else {}


def _referrers(table: str, row: str, ro_hdr: dict):
    """None => the row is already absent; else the list of {fromTable, fromRow,
    columnKey} rows that point AT this one (the onDelete:restrict back-references)."""
    try:
        d = _json(f"{AGENT}/{table}/rows/{row}/referrers", ro_hdr)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    return (d.get("data") or {}).get("referrers") or []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("bundle", help="path to a state/fixtures/<name>.seed.yml (or any bundle)")
    ap.add_argument("--confirm", action="store_true", help="delete (default is dry-run)")
    args = ap.parse_args()

    path = pathlib.Path(args.bundle)
    if not path.is_absolute():
        path = REPO / path
    seed = yaml.safe_load(path.read_text(encoding="utf-8"))
    plan = nos_digest.teardown_plan(seed)
    print(f"teardown plan: {len(plan)} row(s), leaf-first, from {path.name}"
          f"{'  (DRY RUN)' if not args.confirm else ''}")

    H = human_headers()
    ro_hdr = {"Authorization": f"Bearer {_ro_token()}", **proxy_header()}
    deleted = retained = missing = failed = 0
    # Rows we've decided to remove. A referrer that is itself scheduled for
    # removal does NOT retain its target — this simulates the leaf-first cascade
    # so the dry run matches what --confirm actually does (and a referrer from a
    # SURVIVING row, i.e. another firm, correctly retains it).
    planned: set[tuple[str, str]] = set()

    for table, row in plan:
        try:
            refs = _referrers(table, row, ro_hdr)
        except (urllib.error.URLError, OSError) as exc:
            print(f"REFUSING: KEAP referrers probe unreadable ({exc}) — not deleting blind", file=sys.stderr)
            return 2
        if refs is None:
            print(f"  · {table}/{row}: already absent")
            missing += 1
            continue
        survivors = [r for r in refs if (r.get("fromTable"), r.get("fromRow")) not in planned]
        if survivors:
            who = survivors[0]
            print(f"  RETAIN {table}/{row}: referenced by {len(survivors)} surviving row(s) "
                  f"(e.g. {who.get('fromTable')}/{who.get('fromRow')}) — shared, not this firm's alone")
            retained += 1
            continue
        planned.add((table, row))
        if not args.confirm:
            print(f"  [dry] would delete {table}/{row}")
            continue
        try:
            _json(f"{API}/{table}/rows/{row}", H, method="DELETE")
            print(f"  deleted {table}/{row}")
            deleted += 1
        except urllib.error.HTTPError as e:
            print(f"  FAILED  {table}/{row}: {e.code} {e.read().decode()[:120]}", file=sys.stderr)
            failed += 1
            planned.discard((table, row))

    verb = "deleted" if args.confirm else "would delete"
    ndel = deleted if args.confirm else len(planned)
    print(f"\n{verb} {ndel} · retained {retained} · absent {missing}"
          + (f" · FAILED {failed}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
