#!/usr/bin/env python3
"""Move a roadmap row's CLAIM. Not its verdict — that has a different writer.

WHAT WAS MISSING. `tools/roadmap-seed.py` files rows and deliberately never
changes one ("a change to a filed row belongs to the planner, not to a
re-seed"), and the planner is `face-planner` — a row on this very roadmap,
status `next`, not built. So the roadmap delegated its only writer to an item
on itself. Measured 2026-08-08: the live status of all 61 seeded rows was
byte-identical to what the seeder first wrote. Not one row had ever moved, in
either direction, since the day it was filed. Thirty-five rows sat past their
target and no one could tell lateness from unrecorded progress.

This is the missing half, kept deliberately small: it moves `status`, the two
dates that say when something was meant to happen and when it did, and the
`title` — a row's CLAIM of what it is (correcting a title that overstates what
shipped is a claim edit, never a verdict, so it stays on this side of the split).

WHAT IT MUST NOT DO, AND WHY THE SPLIT IS A FILE BOUNDARY. The table's own
definition carries the reason: `status` is what someone CLAIMS, `verified` is
what a PROBE OBSERVED, and conflating them is this estate's most expensive
recurring defect — a queue reporting items pending that were already fixed, a
backup reporting success over empty archives, a container healthy inside a
setup wizard. In every case the success marker was written by the code that
attempted the work.

So this tool cannot write `verified`, `verified_by`, `verified_at` or
`evidence`. There is no flag for them and the write is filtered to an explicit
allow-list, because a writer that COULD certify its own claim will eventually be
asked to. `tools/roadmap-verify.py` owns that half, and there the verdict is
never an argument — it is the exit code of a command the tool runs itself.

The split lives in two files rather than two functions so a gate can see it:
tests/anatomy/test_the_claim_and_the_verdict_have_different_writers.py.

Usage:
    tools/roadmap-update.py --slug agents-inbox --status shipped
    tools/roadmap-update.py --slug sec-p1 --target 2026-08-20
    tools/roadmap-update.py --slug a --slug b --status queued --dry-run
"""

import argparse
import datetime
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

KEAP = "http://127.0.0.1:8091"
TABLE = "2d498264-bc9a-4324-9935-489e5e4d92f3"
from keap_api import human_headers  # noqa: E402 — sibling helper in tools/

#: X-Authentik-* admin identity + the SEC-02 x-keap-proxy-secret (resolved once
#: by keap_api). Without the secret every /api call here 401s since KEAP P1.
HUMAN_HDR = human_headers()

#: The only cells this tool may set. `verified*` and `evidence` are absent on
#: purpose and adding one here is the change the gate exists to refuse. `title`
#: is a claim (what the row IS), not a verdict, so it belongs here.
WRITABLE = {"status", "target", "occurred_at", "owner", "title"}

SHIPPED = "shipped"


def _die(msg: str) -> None:
    sys.exit(f"REFUSING: {msg}")


def _token() -> str:
    tok = os.environ.get("KEAP_AGENT_TOKEN_RW", "").strip()
    if tok:
        return tok
    tok = subprocess.run(
        ["docker", "exec", "iiab-keap-1", "printenv", "KEAP_AGENT_TOKEN_RW"],
        capture_output=True, text=True).stdout.strip()
    if not tok:
        _die("no KEAP_AGENT_TOKEN_RW in the environment and none readable from "
             "iiab-keap-1 — is KEAP running?")
    return tok


def _req(method: str, url: str, headers: dict, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return {"success": False, "error": f"HTTP {exc.code}: {exc.read().decode()[:300]}"}


def _date(s: str) -> int:
    try:
        return int(datetime.datetime.strptime(s, "%Y-%m-%d").timestamp())
    except ValueError:
        _die(f"not a date: {s} (want YYYY-MM-DD)")


def _fmt(ts) -> str:
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d") if ts else "—"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--slug", action="append", required=True,
                    help="row to move; repeatable")
    ap.add_argument("--status", help="new claimed status")
    ap.add_argument("--target", help="YYYY-MM-DD — when it is meant to happen")
    ap.add_argument("--occurred", help="YYYY-MM-DD — when it did (implied by --status shipped)")
    ap.add_argument("--owner", help="who is carrying it")
    ap.add_argument("--title", help="corrected claim of what the row is")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not (args.status or args.target or args.occurred or args.owner or args.title):
        _die("nothing to change — pass at least one of "
             "--status/--target/--occurred/--owner/--title")

    human = f"{KEAP}/api/tables/{TABLE}"
    agent = f"{KEAP}/agent/v1/tables/{TABLE}"

    table = _req("GET", human, HUMAN_HDR)
    if not table.get("success"):
        _die(f"cannot read the table — {table.get('error')}. Is KEAP up?")
    cols = {c["key"]: c
            for c in (table["data"].get("schema", {}).get("columns")
                      or table["data"].get("columns") or [])}

    # A status the live table would reject must fail HERE, naming the options,
    # rather than as a 400 after a partial batch. The live option list and the
    # git-owned definition disagree today (7 vs 11) and the live one is what a
    # write is judged against.
    if args.status:
        allowed = cols.get("status", {}).get("options") or []
        if allowed and args.status not in allowed:
            _die(f"the live table rejects status `{args.status}`.\n"
                 f"  it accepts: {', '.join(allowed)}\n"
                 f"  (state/keap-tables/roadmap.table.yml declares more; the "
                 f"definition has never been applied — see the 409 it returns.)")

    rows = _req("GET", f"{human}/rows?limit=500", HUMAN_HDR)
    if not rows.get("success"):
        _die(f"cannot read rows — {rows.get('error')}")
    by_slug = {r["values"].get("slug"): r for r in rows["data"]["rows"]}

    missing = [s for s in args.slug if s not in by_slug]
    if missing:
        _die(f"no such row(s): {', '.join(missing)}")

    # An upsert against a row whose id is not its slug INSERTS a duplicate
    # instead of updating (the whole reason tools/keap-reid-rows.py exists).
    unkeyed = [s for s in args.slug if by_slug[s]["id"] != s]
    if unkeyed:
        _die("these rows are not addressed by their slug, so a write would "
             f"duplicate them rather than change them: {', '.join(unkeyed)}\n"
             "  run `tools/keap-reid-rows.py --apply` first.")

    agent_hdr = {"authorization": f"Bearer {_token()}", "content-type": "application/json"}
    today = int(datetime.datetime.now().replace(hour=12, minute=0, second=0,
                                                microsecond=0).timestamp())
    changed = 0

    for slug in args.slug:
        cur = by_slug[slug]["values"]
        patch: dict[str, object] = {}
        if args.status and args.status != cur.get("status"):
            patch["status"] = args.status
        if args.target:
            patch["target"] = _date(args.target)
        if args.occurred:
            patch["occurred_at"] = _date(args.occurred)
        elif "status" in patch and args.status == SHIPPED and not cur.get("occurred_at"):
            # `"status" in patch` gates on the TRANSITION, not the argument: only
            # a row actually MOVING to shipped now gets today's date. Without it,
            # re-running --status shipped over a row already shipped WITHOUT a
            # landing date (Planner/agent/seeder writers do not stamp one) stamped
            # today — the rerun date, silently overwriting the real landing.
            # A row that shipped without a landing date is the same conflation
            # the target/occurred_at split exists to end. `target` is left alone
            # on purpose: keeping both is what lets the table answer whether it
            # landed when it was said it would.
            patch["occurred_at"] = today
        if args.owner:
            patch["owner"] = args.owner
        if args.title:
            patch["title"] = args.title

        patch = {k: v for k, v in patch.items() if k in WRITABLE}
        patch = {k: v for k, v in patch.items() if v != cur.get(k)}
        if not patch:
            print(f"  {slug:<28} already there — nothing written")
            continue

        was = ", ".join(
            f"{k} {_fmt(cur.get(k)) if k in ('target', 'occurred_at') else cur.get(k) or '—'}"
            f" -> {_fmt(v) if k in ('target', 'occurred_at') else v}"
            for k, v in patch.items())
        print(f"  {slug:<28} {was}")
        if args.dry_run:
            changed += 1
            continue

        # The agent door validates the WHOLE row, not the diff, so the required
        # cells ride along unchanged. Everything else is left to the merge.
        body = {"slug": slug, "title": cur.get("title"), **patch}
        res = _req("POST", f"{agent}/rows", agent_hdr, body)
        if not res.get("success"):
            _die(f"writing {slug} failed — {res.get('error')}")
        changed += 1

    if args.dry_run:
        print(f"\nDRY RUN — nothing written. {changed} row(s) would change.")
    else:
        print(f"\n{changed} row(s) changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
