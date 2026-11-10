#!/usr/bin/env python3
"""Dispatch every scheduled GitHub workflow on dev: GitHub fires `schedule` only on master.

Row ci-circadian (operator 2026-11-10). Between releases dev carried a nightly lane
(NOS_LANE=all), the FrankenPHP re-pin and the cold-file watch that never ran, because
schedules read the default branch. A Pulse job runs this each night (plugin ci-circadian,
off by default: a client estate never dispatches our CI). A workflow qualifies when it has
both `schedule` and `workflow_dispatch`, so a new nightly workflow needs no edit here.

    tools/ci-circadian.py              # gh workflow run <each> --ref dev
    tools/ci-circadian.py --dry-run    # list what it would dispatch

Exit: 0 all dispatched · 11 gh missing, unauthenticated or a dispatch refused.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
REF = "dev"


def scheduled() -> list[str]:
    out = []
    for p in sorted((REPO / ".github/workflows").glob("*.yml")):
        doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        on = doc.get("on") or doc.get(True) or {}
        if isinstance(on, dict) and "schedule" in on and "workflow_dispatch" in on:
            out.append(p.name)
    return out


def github_repo() -> str | None:
    url = subprocess.run(["git", "-C", str(REPO), "remote", "get-url", "origin"],
                         capture_output=True, text=True).stdout.strip()
    m = re.search(r"github\.com[:/]([\w.-]+/[\w.-]+?)(?:\.git)?$", url)
    return m[1] if m else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    flows, repo = scheduled(), github_repo()
    if not repo:
        print("ci-circadian: origin is not a GitHub remote; nothing to dispatch", file=sys.stderr)
        return 11
    if args.dry_run:
        print("\n".join(f"would dispatch {f} on {repo}@{REF}" for f in flows))
        return 0
    bad = []
    for f in flows:
        r = subprocess.run(["gh", "workflow", "run", f, "--ref", REF, "-R", repo],
                           capture_output=True, text=True, timeout=60)
        print(f"{'dispatched' if r.returncode == 0 else 'REFUSED'} {f}@{REF}")
        if r.returncode:
            bad.append(f)
            print(r.stderr.strip()[-300:], file=sys.stderr)
    return 11 if bad else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except FileNotFoundError:
        print("ci-circadian: gh is not installed", file=sys.stderr)
        sys.exit(11)
