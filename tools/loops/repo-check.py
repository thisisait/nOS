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

# Step id → argv0 relative to the repo. Must match repo-check.loop.yml step ids.
STEPS = (
    ("red-status", "tools/red-status.py"),
    ("estate-status", "tools/estate-status.py"),
    ("forge-sync", "tools/forge-sync.py"),
)

_FORBIDDEN = ("--apply", "--push-github")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if any(a in _FORBIDDEN for a in argv):
        print("repo-check is report-only — refused an apply flag", file=sys.stderr)
        return 2
    py = sys.executable
    spawned = 0
    for sid, rel in STEPS:
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
        spawned += 1
    return 0 if spawned == len(STEPS) else 2


if __name__ == "__main__":
    raise SystemExit(main())
