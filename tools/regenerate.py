#!/usr/bin/env python3
"""Regenerate every stale generated file: one command for what one gate checks.

Roadmap row `gate-diet-freshness-one`. For each `check` in state/generated.yml, in
registry order (graph before body plan before imprint), a failing check runs its
writer (the same argv without --check); the anatomy graph also re-freezes the face
layout pin. Gate: tests/anatomy/test_generated_files_hold.py.

    python3 tools/regenerate.py            # rewrite what is stale, list what it wrote
    python3 tools/regenerate.py --check    # exit 1 and name the stale checks
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]


def checks() -> list[list[str]]:
    files = yaml.safe_load((REPO / "state/generated.yml").read_text(encoding="utf-8"))["files"]
    out: list[list[str]] = []
    for entry in files.values():
        if entry.get("check") and entry["check"] not in out:
            out.append(entry["check"])
    return out


def run(argv: list[str]) -> bool:
    return subprocess.run([sys.executable, *argv], cwd=REPO, capture_output=True).returncode == 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if anything is stale")
    args = ap.parse_args()
    stale: list[str] = []
    for _ in range(3):  # a later writer can stale an earlier file; repeat until a quiet pass
        wrote = False
        for check in checks():
            if run(check):
                continue
            if " ".join(check) not in stale:
                stale.append(" ".join(check))
            if args.check:
                continue
            writer = [a for a in check if a != "--check"]
            if writer[0] == "tools/anatomy-graph-gen.py":
                writer.append("--refreeze")
            if not run(writer) or not run(check):
                print(f"regenerate: {' '.join(writer)} did not make its check pass", file=sys.stderr)
                return 1
            wrote = True
        if not wrote:
            break
    for s in stale:
        print(f"{'stale' if args.check else 'rewrote'}: {s}")
    return 1 if args.check and stale else 0


if __name__ == "__main__":
    sys.exit(main())
