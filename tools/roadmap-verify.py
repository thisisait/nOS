#!/usr/bin/env python3
"""Write a roadmap row's VERDICT — which is an exit code, never an argument.

THE COLUMN THAT EXISTED AND NOBODY FILLED. `state/keap-tables/roadmap.table.yml`
declares `verified` / `verified_by` / `verified_at` / `evidence` and explains
exactly why they sit beside `status`:

    status    — what someone CLAIMS. Written by whoever files or does the work.
    verified  — what a PROBE OBSERVED. Written only by an independent check.
    […] A row whose `status` says done and whose `verified` says contradicted is
    the most useful row this table can hold, and it is unreachable in any design
    where one writer owns both.

Measured 2026-08-08: 68 of 68 rows carried no verification. The columns had been
live for a day and had never been written, because nothing could write them.

WHY THERE IS NO --verdict FLAG. If the verdict were an argument, this tool would
be a second way to make a claim, and the estate has paid for that shape
repeatedly: `dispatched_at` stamped by the sender even on failure; `status=scanned`
written by a scan that never ran; "Backup OK — N sources" over empty archives.
The doctrine that came out of it is one line — *a success marker must be written
by a reader, not by the attempting code* — and the cheapest way to obey it is to
make the marker inexpressible.

So the verdict is produced, not supplied:

    --by "<command>"   the command RUNS. exit 0 -> confirmed. non-zero -> contradicted.
    --unverifiable "…" no command exists for this row; say why, and that is the verdict.

`unverifiable` is not a failure — it is an honest third answer, and it is what
keeps the other two meaningful. A row nobody can probe should say so rather than
inherit `unverified` forever or borrow a neighbour's evidence.

This tool cannot write `status`. `tools/roadmap-update.py` owns the claim, this
one owns the verdict, and the split is two files so a gate can see it:
tests/anatomy/test_the_claim_and_the_verdict_have_different_writers.py.

A NOTE ON WHAT LANDS IN `evidence`. The command's output is stored and the face
renders it. Choose probes whose output is a fact, not a secret — this captures
what you ran it with, and it cannot know which bytes you would not want read.

Usage:
    tools/roadmap-verify.py --slug agents-inbox \
        --by 'test -f files/anatomy/wing/app/Model/AgentQuestionRepository.php'
    tools/roadmap-verify.py --slug cortex-exec \
        --by 'test -d files/anatomy/wing/app/Cortex'
    tools/roadmap-verify.py --slug sere-hosts --unverifiable 'no host to probe yet'
"""

import argparse
import datetime
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PROBES = REPO / "state/roadmap-probes.yml"
KEAP = "http://127.0.0.1:8091"
TABLE = "2d498264-bc9a-4324-9935-489e5e4d92f3"
from keap_api import human_headers  # noqa: E402 — sibling helper in tools/

#: X-Authentik-* admin identity + the SEC-02 x-keap-proxy-secret (resolved once
#: by keap_api). Without the secret every /api call here 401s since KEAP P1.
HUMAN_HDR = human_headers()

#: The only cells this tool may set. `status` is absent on purpose.
WRITABLE = {"verified", "verified_by", "verified_at", "evidence"}

OUTPUT_CAP = 2000


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


def run_catalogue(args) -> int:
    """Run every probe in state/roadmap-probes.yml and report the disagreements.

    The interesting output is not the tally, it is the two mismatch classes:
    a row claiming `shipped` that the estate contradicts, and a row still
    `queued` whose deliverable is already there. The second is what 35 overdue
    rows turned out to be made of.
    """
    import yaml

    if not PROBES.exists():
        _die(f"no probe catalogue at {PROBES}")
    catalogue = yaml.safe_load(PROBES.read_text(encoding="utf-8")) or {}

    rows = _req("GET", f"{KEAP}/api/tables/{TABLE}/rows?limit=500", HUMAN_HDR)
    if not rows.get("success"):
        _die(f"cannot read rows — {rows.get('error')}. Is KEAP up?")
    by_slug = {r["values"].get("slug"): r for r in rows["data"]["rows"]}

    unknown = sorted(set(catalogue) - set(by_slug))
    if unknown:
        _die("the catalogue names rows the table does not hold: " + ", ".join(unknown))

    argv = [sys.executable, os.path.abspath(__file__)]
    tally: dict[str, int] = {}
    mismatch: list[tuple[str, str, str]] = []
    for slug, probe in catalogue.items():
        cmd = argv + ["--slug", slug]
        cmd += (["--unverifiable", probe["unverifiable"]]
                if isinstance(probe, dict) else ["--by", probe])
        if args.dry_run:
            cmd.append("--dry-run")
        proc = subprocess.run(cmd, capture_output=True, text=True)
        line = next((ln for ln in proc.stdout.splitlines() if "verified" in ln), "")
        verdict = line.rsplit("-> ", 1)[-1].strip() if line else "?"
        # A verdict counts only if the child that wrote it EXITED 0. The child
        # prints "verified -> X" BEFORE its POST, so a failed write still emits
        # the line — tallying it here counts verdicts that never landed (the
        # success-written-by-the-attempting-code defect this file is named for).
        if not line or proc.returncode != 0:
            print(f"  {slug:<24} {'WRITE FAILED' if line else 'PROBE FAILED TO RUN'}")
            print((proc.stderr or proc.stdout).strip()[:300])
            tally["?"] = tally.get("?", 0) + 1
            continue
        tally[verdict] = tally.get(verdict, 0) + 1
        status = by_slug[slug]["values"].get("status")
        flag = ""
        if verdict == "confirmed" and status not in ("shipped", "dropped"):
            flag, _ = "  <-- DONE, and the row does not say so", mismatch.append(
                (slug, status, verdict))
        elif verdict == "contradicted" and status == "shipped":
            flag, _ = "  <-- claims shipped, estate disagrees", mismatch.append(
                (slug, status, verdict))
        print(f"  {slug:<24} {status:<8} {verdict:<13}{flag}")

    print("\n" + " · ".join(f"{n} {k}" for k, n in sorted(tally.items())))
    if mismatch:
        print(f"\n{len(mismatch)} row(s) where the claim and the estate disagree:")
        for slug, status, verdict in mismatch:
            print(f"  {slug:<24} status={status:<8} verified={verdict}")
        print("  move them with tools/roadmap-update.py — this tool never will.")
    if args.dry_run:
        print("\nDRY RUN — nothing written.")
    # A disagreement is a successful verification, so it is not an error exit;
    # 3 is reserved for "something was contradicted" the same as the single-row
    # path, so a scheduler can key a finding on it.
    return 3 if any(v == "contradicted" for _, _, v in mismatch) else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--slug")
    ap.add_argument("--by", help="command to run; its exit code IS the verdict")
    ap.add_argument("--unverifiable", metavar="REASON",
                    help="no probe exists for this row; the reason is the record")
    ap.add_argument("--all", action="store_true",
                    help=f"run every probe in {PROBES.name}")
    ap.add_argument("--cwd", default=None, help="where to run --by (default: repo root)")
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.all:
        if args.slug or args.by or args.unverifiable:
            _die("--all runs the catalogue; it takes no --slug/--by/--unverifiable")
        return run_catalogue(args)

    if not args.slug:
        _die("pass --slug, or --all to run the catalogue")
    if bool(args.by) == bool(args.unverifiable):
        _die("pass exactly one of --by (a probe that produces the verdict) or "
             "--unverifiable (a reason no probe exists).")

    human = f"{KEAP}/api/tables/{TABLE}"
    agent = f"{KEAP}/agent/v1/tables/{TABLE}"

    rows = _req("GET", f"{human}/rows?limit=500", HUMAN_HDR)
    if not rows.get("success"):
        _die(f"cannot read rows — {rows.get('error')}. Is KEAP up?")
    row = next((r for r in rows["data"]["rows"]
                if r["values"].get("slug") == args.slug), None)
    if row is None:
        _die(f"no such row: {args.slug}")
    if row["id"] != args.slug:
        _die(f"row `{args.slug}` is addressed by `{row['id']}`, so a write would "
             "duplicate it — run `tools/keap-reid-rows.py --apply` first.")

    now = int(datetime.datetime.now().timestamp())

    if args.unverifiable:
        verdict = "unverifiable"
        by = "no probe"
        evidence = {"reason": args.unverifiable, "at": now}
    else:
        cwd = args.cwd or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        try:
            proc = subprocess.run(args.by, shell=True, cwd=cwd, capture_output=True,
                                  text=True, timeout=args.timeout)
            rc, out, err = proc.returncode, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired:
            # A probe that never answered observed nothing. Calling that
            # `contradicted` would put a finding in the table that no one made.
            rc, out, err = None, "", f"timed out after {args.timeout}s"
        verdict = ("unverifiable" if rc is None
                   else "confirmed" if rc == 0 else "contradicted")
        by = args.by
        evidence = {"command": args.by, "cwd": cwd, "exit": rc,
                    "stdout": out[-OUTPUT_CAP:], "stderr": err[-OUTPUT_CAP:], "at": now}

    was = row["values"].get("verified") or "unverified"
    print(f"  {args.slug:<28} verified {was} -> {verdict}")
    if not args.unverifiable:
        print(f"    ran: {args.by}")
        print(f"    exit: {evidence['exit']}")
        tail = (evidence["stdout"] or evidence["stderr"]).strip().splitlines()
        for line in tail[-3:]:
            print(f"    | {line[:110]}")

    if args.dry_run:
        print("\nDRY RUN — nothing written.")
        return 0

    patch = {"verified": verdict, "verified_by": by, "verified_at": now,
             "evidence": evidence}
    patch = {k: v for k, v in patch.items() if k in WRITABLE}
    # Only the verified* cells + the slug that keys the upsert. The agent door
    # MERGES the patch into the existing row ({...existing, ...values}) and
    # validates the MERGED result, so required columns need not ride along — and
    # must NOT: merge overwrites whatever keys `values` carries, so sending the
    # status/title read at sweep start would REVERT a status/title a concurrent
    # roadmap-update.py landed in the meantime. Omitting them lets the merge keep
    # the current value, which is also exactly the "never move the claim" rule
    # this file exists to enforce.
    body = {"slug": args.slug, **patch}
    res = _req("POST", f"{agent}/rows", {"authorization": f"Bearer {_token()}",
                                         "content-type": "application/json"}, body)
    if not res.get("success"):
        _die(f"writing {args.slug} failed — {res.get('error')}")
    print("\nwritten.")

    # The verdict is the row's, not this process's: a `contradicted` row is a
    # successful verification. But a caller scripting a sweep needs to know one
    # came back contradicted without re-reading the table, so say it in the code.
    return 0 if verdict != "contradicted" else 3


if __name__ == "__main__":
    raise SystemExit(main())
