#!/usr/bin/env python3
"""repo-check runner — the three readers behind files/anatomy/loops/repo-check.loop.yml.

THE MANIFEST is the loop's source (graph + pulse job). This file only runs the
steps. forge-sync is invoked with no flags: that is the dry-run report.
`--apply` / `--push-github` are refused here, not hoped away at the call site.

Exit: 0 every reader spawned · 2 a reader was missing or could not start.
A reader that finds red or drift keeps its own exit code in the log; this
process does not launder or escalate it. Pulse stores the tails.
"""

from __future__ import annotations

import os
import subprocess
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

# Step id → (argv0 relative to the repo, is_gate). Must match the manifest's
# step ids.
#
# READERS (is_gate False) exit 0 whatever they find; their code is logged and
# passed through, never escalated — that is the promise in the docstring above.
#
# A GATE exits non-zero to MEAN something. caddy-wording-coverage's own
# docstring: "Exit 0 iff coverage is 100%". Treating it as a reader would leave
# a wording regression as an rc=1 line in a log nobody opens, so a failing gate
# makes this loop return 3 and the manifest declares that a FINDING.
STEPS = (
    ("red-status", "tools/red-status.py", False),
    ("estate-status", "tools/estate-status.py", False),
    ("forge-sync", "tools/forge-sync.py", False),
    ("wording-coverage", "tools/caddy-wording-coverage.py", True),
)

#: Exit code meaning "a gate step reported a finding" (manifest:
#: findings_exit_codes).
FINDINGS = 3

_FORBIDDEN = ("--apply", "--push-github")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if any(a in _FORBIDDEN for a in argv):
        print("repo-check is report-only — refused an apply flag", file=sys.stderr)
        return 2
    py = sys.executable
    spawned = 0
    findings: list[str] = []
    for sid, rel, is_gate in STEPS:
        path = os.path.join(REPO, rel)
        print(f"\n===== {sid} =====", flush=True)
        if not os.path.isfile(path):
            print(f"missing {rel}", file=sys.stderr)
            return 2
        try:
            proc = subprocess.run([py, path], cwd=REPO)
        except OSError as exc:
            print(f"{sid} could not start: {exc}", file=sys.stderr)
            return 2
        print(f"----- {sid} rc={proc.returncode} -----", flush=True)
        if is_gate and proc.returncode != 0:
            findings.append(f"{sid} (rc={proc.returncode})")
        spawned += 1
    if spawned != len(STEPS):
        return 2
    if findings:
        print(f"\nFINDING: gate step(s) reported: {', '.join(findings)}", flush=True)
        return FINDINGS
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
