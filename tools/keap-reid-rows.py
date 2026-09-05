#!/usr/bin/env python3
"""Make every row of a KEAP DataTable addressable by its own business key.

WHY THIS EXISTS — measured 2026-08-08 on the nOS Roadmap table.

A KEAP row has two names: the ROW ID it is addressed by, and whatever its
`slug` (or other key) CELL happens to say. Which one you get depends on the door
you came through:

  POST /api/tables/<t>/rows        (human API, forward-auth)  -> row id = a UUID
  POST /agent/v1/tables/<t>/rows   (agent API, bearer)        -> row id = the slug cell

And the agent route is the only one that can UPDATE a row — the human API has
create and delete and nothing else (PATCH and PUT both answer 404, verified).
That route's "upsert" keys on the ROW ID. So against rows minted through the
human door, an upsert matches nothing and silently INSERTS a second row.

Reproduced by accident while probing: writing `status` to `agents-inbox` did not
change it, it created a duplicate whose row id was literally `agents-inbox`
beside the original whose id was `04b8a900-…`. Both rows then claimed the same
slug. The duplicate was deleted; the lesson is what stayed.

The consequence is bigger than one probe. Every roadmap row was created through
the human door, so NOTHING could ever update one — not `tools/roadmap-seed.py`
(which is additive by design), not the face grid (whose BFF writes through the
agent upsert), not the Planner that does not exist yet. The roadmap's status
column had been byte-identical to what the seeder first wrote for 68/68 rows,
and this is the mechanism.

WHAT THIS DOES. For each row whose id is not its key cell: create the row again
through the agent door — which mints the id from the key — then delete the
original. Values are carried verbatim and compared afterwards.

WHY IT IS NOT A ONE-SHOT. The property "a row is addressable by its key" is one
any writer can break again by using the human door, and `tools/discovery-scan.py`
did exactly that every night. Re-running this repairs it; running it when
nothing is wrong reports 0 and writes nothing.

Usage:
    tools/keap-reid-rows.py [--table <id>] [--key slug] [--apply]

Dry run unless --apply. A dry run that skipped the checks would rehearse a
different operation than the one it claims to rehearse, so every refusal below
is evaluated in both modes.
"""

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request

KEAP = "http://127.0.0.1:8091"
ROADMAP = "2d498264-bc9a-4324-9935-489e5e4d92f3"
HUMAN_HDR = {
    "X-Authentik-Username": "akadmin",
    "X-Authentik-Email": "admin@pazny.eu",
    "X-Authentik-Groups": "nos-providers,nos-admins",
    "Content-Type": "application/json",
}


def _die(msg: str) -> None:
    sys.exit(f"REFUSING: {msg}")


def _token() -> str:
    """The RW agent token. Env first; otherwise the running container, which is
    the only other place it exists on a converged host — it is a derived
    `{prefix}_pw_keap_agent_rw`, so it is not in ~/.nos/secrets.yml."""
    import os
    tok = os.environ.get("KEAP_AGENT_TOKEN_RW", "").strip()
    if tok:
        return tok
    r = subprocess.run(
        ["docker", "exec", "iiab-keap-1", "printenv", "KEAP_AGENT_TOKEN_RW"],
        capture_output=True, text=True)
    tok = r.stdout.strip()
    if not tok:
        _die("no KEAP_AGENT_TOKEN_RW in the environment and none readable from "
             "iiab-keap-1 — is KEAP running? (`docker ps --filter name=keap`)")
    return tok


def _req(method: str, url: str, headers: dict, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return {"success": False, "error": f"HTTP {exc.code}: {exc.read().decode()[:300]}"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--table", default=ROADMAP, help="table id (default: the nOS Roadmap)")
    ap.add_argument("--key", default="slug", help="column holding the business key")
    ap.add_argument("--apply", action="store_true", help="write (default: dry run)")
    args = ap.parse_args()

    human = f"{KEAP}/api/tables/{args.table}"
    agent = f"{KEAP}/agent/v1/tables/{args.table}"
    agent_hdr = {"authorization": f"Bearer {_token()}", "content-type": "application/json"}

    table = _req("GET", human, HUMAN_HDR)
    if not table.get("success"):
        _die(f"cannot read the table — {table.get('error')}")
    schema = table["data"].get("schema", {})
    cols = {c["key"]: c for c in (schema.get("columns") or table["data"].get("columns") or [])}
    if args.key not in cols:
        _die(f"the table has no `{args.key}` column — nothing to key a row on")
    required = sorted(k for k, c in cols.items() if c.get("required"))

    rows = _req("GET", f"{human}/rows?limit=500", HUMAN_HDR)
    if not rows.get("success"):
        _die(f"cannot read rows — {rows.get('error')}")
    rows = rows["data"]["rows"]
    print(f"{len(rows)} row(s) · key column `{args.key}` · required: {', '.join(required)}")

    # A key that two rows share cannot name one row, so re-identifying either
    # would silently merge them. Refuse before writing, not halfway through.
    seen: dict[str, int] = {}
    for r in rows:
        seen[str(r["values"].get(args.key))] = seen.get(str(r["values"].get(args.key)), 0) + 1
    dupes = sorted(k for k, n in seen.items() if n > 1)
    if dupes:
        _die(f"these key values name more than one row: {', '.join(dupes)}")

    stale = [r for r in rows if r["id"] != str(r["values"].get(args.key))]
    if not stale:
        print("every row is already addressable by its key — nothing to do.")
        return 0

    # The agent door validates the whole row, not the diff. A row missing a
    # required cell would fail mid-migration and leave the table half-moved.
    incomplete = [
        (r["values"].get(args.key), [k for k in required if not r["values"].get(k)])
        for r in stale
    ]
    incomplete = [(s, miss) for s, miss in incomplete if miss]
    if incomplete:
        _die("these rows lack a required cell and the agent door would reject them:\n  "
             + "\n  ".join(f"{s}: missing {', '.join(m)}" for s, m in incomplete))

    print(f"{len(stale)} row(s) addressed by something other than their key:")
    for r in stale[:5]:
        print(f"  {r['values'].get(args.key):<28} id={r['id']}")
    if len(stale) > 5:
        print(f"  … and {len(stale) - 5} more")

    if not args.apply:
        print("\nDRY RUN — nothing written. Re-run with --apply.")
        return 0

    # Create first, delete second. The reverse order risks a row existing in
    # neither place if this dies mid-way; this way the worst case is a visible
    # duplicate, which the next run reports rather than hides.
    made, removed = 0, 0
    for r in stale:
        res = _req("POST", f"{agent}/rows", agent_hdr, r["values"])
        if not res.get("success"):
            _die(f"creating {r['values'].get(args.key)} failed — {res.get('error')}\n"
                 f"  {made} row(s) already re-created; the originals are untouched.")
        made += 1
    # Delete an original ONLY after confirming its re-created twin actually
    # exists keyed by the business key. The agent door mints the row id from the
    # `slug` cell (or a fresh UUID) — NOT from an arbitrary --key — so a re-id by
    # any other column silently lands under a UUID, and the old code deleted the
    # original anyway (data loss; the mismatch check ran too late). Verify first;
    # a twin that did not land leaves the original in place and a visible
    # duplicate the next run reports.
    now_ids = {row["id"] for row in
               _req("GET", f"{human}/rows?limit=500", HUMAN_HDR)["data"]["rows"]}
    removed, skipped = 0, 0
    for r in stale:
        key_val = str(r["values"].get(args.key))
        if key_val not in now_ids:
            print(f"  SKIP {key_val}: re-id did not land (door kept id {r['id']}); "
                  "original preserved, duplicate remains — the door cannot key on "
                  f"`{args.key}` (only `slug`).")
            skipped += 1
            continue
        res = _req("DELETE", f"{human}/rows/{r['id']}", HUMAN_HDR)
        if not res.get("success"):
            _die(f"deleting the original of {key_val} failed — "
                 f"{res.get('error')}\n  {removed} removed; the table now holds duplicates.")
        removed += 1
    if skipped:
        print(f"\n{skipped} row(s) NOT re-keyed — the agent door mints ids from "
              f"`slug`, not `{args.key}`. No original was lost.")

    after = _req("GET", f"{human}/rows?limit=500", HUMAN_HDR)["data"]["rows"]
    before_vals = sorted(json.dumps(r["values"], sort_keys=True) for r in rows)
    after_vals = sorted(json.dumps(r["values"], sort_keys=True) for r in after)
    mismatched = [r["id"] for r in after if r["id"] != str(r["values"].get(args.key))]
    print(f"\nre-created {made} · deleted {removed} · rows now {len(after)}")
    print(f"  values identical to before: {before_vals == after_vals}")
    print(f"  rows still not keyed by `{args.key}`: {len(mismatched)}")
    if before_vals != after_vals or mismatched or len(after) != len(rows):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
