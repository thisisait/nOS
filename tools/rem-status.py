#!/usr/bin/env python3
"""What the security queue says, right now.

WHY THIS EXISTS. `CLAUDE.md` carried the queue's tally as prose — "N pending /
M resolved of T" — and it was wrong three times in four months. Every time for
the same reason: a number copied forward by a reader who had no cheap way to
re-derive it. The paragraph even said so about itself, twice, and asked the
next reader to re-derive by hand.

Asking a document to hold a moving number is the mistake. The estate should
answer the question; the document should name the question. This is the answer
half — after it, `CLAUDE.md` names the command and keeps only the part that is
knowledge rather than state (why a row was hard, what class of blindness the
queue has).

It reads the file and nothing else: no network, no Docker, no daemon. For "is a
pending row already fixed on the running estate", that is
`tools/discovery-scan.py`, which compares against `docker ps` and files a
roadmap row — a different question with a different cost.

Usage:
    tools/rem-status.py            # the tally, and every pending HIGH/CRITICAL
    tools/rem-status.py --all      # every pending row
    tools/rem-status.py --json     # for a caller

Exit 0 always. This reports; it does not judge. A gate that went red because
upstream published a CVE would be red on a calendar, not on a defect.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
QUEUE = REPO / "docs/llm/security/remediation-queue.json"

#: Worst first. Anything not in this list sorts last under its own name, so a
#: severity the scanner invents tomorrow is visible rather than dropped.
SEVERITY_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]


def load() -> list[dict]:
    raw = json.loads(QUEUE.read_text(encoding="utf-8"))
    return raw["items"] if isinstance(raw, dict) and "items" in raw else raw


#: A row is CLOSED when it stops being work. Each of these is a claim that
#: something is no longer owed, and a claim is the thing this estate insists
#: must carry its evidence.
CLOSED_STATUSES = ("resolved", "wontfix", "obsolete", "vendor-blocked")

#: Any ONE of these is evidence enough. The bar is deliberately low — the
#: finding is not "the prose is thin", it is "there is nothing at all".
EVIDENCE_FIELDS = ("resolved_by", "resolution", "resolved_detail",
                   "blocked_reason", "decision")


def unproven(items: list[dict]) -> list[dict]:
    """Closed rows carrying no evidence of any kind.

    WHAT THIS MEASURES, AND WHY IT IS NOT THE THING THE ROADMAP ASKED FOR.
    `sec-queue-authorship` says the nightly scan overwrites what a human wrote,
    citing REM-144 losing its disposition for a day. Checked 2026-08-22 across
    all 75 commits that ever touched this file: **zero** dispositions were ever
    lost. REM-144's own `resolved_detail` says what actually happened — the
    record "carried a bare status+date until then, with no resolved_by and no
    evidence". Not an overwrite. An assertion nobody had to back.

    Measured the same day: 50 of 155 closed rows carry nothing — 48 `resolved`,
    one `obsolete`, one `wontfix` — and among them are CRITICALs on portainer,
    traefik and five n8n rows. Roughly a third of everything this queue says is
    finished is unfalsifiable, and the cost is legible in REM-144: a reader in
    August had to re-derive from scratch whether a CRITICAL was really closed.

    So this is the honest half of that row. It is a READER: it counts and names,
    and closing a row stays a deliberate act with the evidence written in.
    """
    return [i for i in items
            if i.get("status") in CLOSED_STATUSES
            and not any(i.get(f) for f in EVIDENCE_FIELDS)]


#: A row below HIGH is deferrable only if it has something to WAIT FOR. Measured
#: 2026-08-22: of 45 pending rows below HIGH, 15 are `version_bump` and 30 are
#: not — 21 of those 30 are `config_change`. A release boundary moves pins; it
#: does nothing whatever for a config change, so "batch everything below HIGH to
#: the next tag" relabels 30 actionable rows as upstream-gated and conserves no
#: effort at all.
#:
#: So the lane is picked by what the row is BLOCKED ON, and severity picks only
#: what must be noticed now. This is the whole of the severity floor that
#: survived a four-design panel on 2026-08-22; the rest is recorded as refused
#: in docs/doctrine/security-floor.md.
WAITS_FOR_A_TAG = ("version_bump",)


def lanes(items: list[dict]) -> dict[str, list[dict]]:
    """Pending rows split by what each is actually waiting for."""
    pending = [i for i in items if i.get("status") == "pending"]
    act = [i for i in pending if i.get("severity") in ("CRITICAL", "HIGH")]
    below = [i for i in pending if i not in act]
    return {
        "act_now": act,
        "waits_for_a_tag": [i for i in below
                            if i.get("remediation_type") in WAITS_FOR_A_TAG],
        "waits_for_nobody": [i for i in below
                             if i.get("remediation_type") not in WAITS_FOR_A_TAG],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--all", action="store_true", help="list every pending row, not only HIGH+")
    ap.add_argument("--json", action="store_true", help="machine-readable")
    ap.add_argument("--unproven", action="store_true",
                    help="list CLOSED rows that carry no evidence at all")
    ap.add_argument("--floor", action="store_true",
                    help="pending rows split by what each is waiting for")
    args = ap.parse_args()

    items = load()
    pending = [i for i in items if i.get("status") == "pending"]
    by_status = collections.Counter(i.get("status") for i in items)
    by_sev = collections.Counter(i.get("severity") for i in pending)
    cycle = max((i.get("scan_cycle") or 0) for i in items) if items else 0

    if args.json:
        json.dump(
            {
                "file": str(QUEUE.relative_to(REPO)),
                "total": len(items),
                "by_status": dict(by_status),
                "pending_by_severity": dict(by_sev),
                "scan_cycle": cycle,
                "unproven_closures": len(unproven(items)),
                "pending": [
                    {k: i.get(k) for k in ("id", "severity", "component",
                                           "current_version", "fix_version")}
                    for i in pending
                ],
            },
            sys.stdout,
            indent=1,
        )
        print()
        return 0

    print(f"{QUEUE.relative_to(REPO)} — cycle {cycle}, {len(items)} rows")
    print("  " + " · ".join(f"{n} {s}" for s, n in by_status.most_common()))
    sev = " · ".join(
        f"{by_sev.get(s, 0)} {s}" for s in SEVERITY_ORDER if by_sev.get(s)
    )
    extra = [s for s in by_sev if s not in SEVERITY_ORDER]
    if extra:
        sev += " · " + " · ".join(f"{by_sev[s]} {s}" for s in extra)
    print(f"  pending by severity: {sev or 'none'}")

    bare = unproven(items)
    if bare:
        closed = sum(1 for i in items if i.get("status") in CLOSED_STATUSES)
        print(f"  {len(bare)} of {closed} CLOSED rows carry no evidence "
              f"— `--unproven` names them")

    if args.floor:
        lane = lanes(items)
        print()
        print(f"  act now — CRITICAL/HIGH                      {len(lane['act_now']):>3}")
        print(f"  below HIGH, waits for a tag (version_bump)   {len(lane['waits_for_a_tag']):>3}")
        print(f"  below HIGH, waits for NOBODY                 {len(lane['waits_for_nobody']):>3}")
        print()
        print("  The third lane is the finding. A release boundary moves pins and")
        print("  does nothing for a config change, so deferring it to the next tag")
        print("  relabels work rather than scheduling it.\n")
        for i in sorted(lane["waits_for_nobody"],
                        key=lambda x: (str(x.get("remediation_type")), x.get("id", ""))):
            print(f"  {i.get('id',''):<9} {str(i.get('severity','?')):<7} "
                  f"{str(i.get('remediation_type','?')):<22} {str(i.get('component','?'))}")
        return 0

    if args.unproven:
        print()
        if not bare:
            print("  every closed row carries evidence.")
            return 0
        print(f"  CLOSED WITHOUT EVIDENCE — {len(bare)} row(s), worst first.")
        print("  Not a defect list: a list of claims nobody has to believe.\n")
        for i in sorted(bare, key=lambda x: (SEVERITY_ORDER.index(x["severity"])
                                             if x.get("severity") in SEVERITY_ORDER
                                             else len(SEVERITY_ORDER), x.get("id", ""))):
            print(f"  {i.get('id',''):<9} {str(i.get('severity','?')):<9} "
                  f"{str(i.get('status','?')):<14} {str(i.get('component','?')):<14} "
                  f"closed {i.get('resolved_at') or 'undated'}")
        return 0

    show = pending if args.all else [i for i in pending
                                     if i.get("severity") in ("CRITICAL", "HIGH")]
    if show:
        print()
        for i in sorted(show, key=lambda x: (SEVERITY_ORDER.index(x["severity"])
                                             if x.get("severity") in SEVERITY_ORDER
                                             else len(SEVERITY_ORDER), x.get("id", ""))):
            cur = str(i.get("current_version") or "?")
            fix = str(i.get("fix_version") or "?")
            print(f"  {i.get('id'):<9} {i.get('severity'):<8} {i.get('component'):<14} "
                  f"{cur[:40]} -> {fix[:40]}")
    if not args.all and pending:
        rest = len(pending) - len(show)
        if rest:
            print(f"\n  +{rest} pending below HIGH — `--all` lists them.")

    # A pending row may simply be stale: the estate can be fixed while the queue
    # is not. Say so here rather than letting a count imply exposure.
    print("\n  A pending row is not proof of exposure — twelve rows so far were "
          "already live at their\n  fix version. `tools/discovery-scan.py` compares "
          "the queue against `docker ps`.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
