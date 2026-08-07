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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--all", action="store_true", help="list every pending row, not only HIGH+")
    ap.add_argument("--json", action="store_true", help="machine-readable")
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
