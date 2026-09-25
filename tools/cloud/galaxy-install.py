#!/usr/bin/env python3
"""Install requirements.lock.yml — from Galaxy when it answers, from git when not.

A Claude cloud session's egress policy refuses galaxy.ansible.com (403 on
CONNECT) while github.com is open. The pins stay in requirements.lock.yml;
tools/cloud/galaxy-git-sources.yml only says where each one lives on GitHub.

    tools/cloud/galaxy-install.py                 # auto: probe Galaxy, fall back to git
    tools/cloud/galaxy-install.py --source git    # force the git path
    tools/cloud/galaxy-install.py --check         # print the plan, install nothing
    tools/cloud/galaxy-install.py --probe         # exit 0 iff Galaxy answers

Idempotent: ansible-galaxy itself skips a collection or role already installed
at the pinned version.

Uses the `ansible-galaxy` on PATH and the caller's ANSIBLE_HOME, so the frozen
venv (.ci-venv/ansible-home) stays the only place this writes.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
LOCK = REPO / "requirements.lock.yml"
SOURCES = REPO / "tools" / "cloud" / "galaxy-git-sources.yml"
GALAXY_PROBE = "https://galaxy.ansible.com/api/"


def galaxy_reachable(timeout: float = 10.0) -> bool:
    try:
        with urllib.request.urlopen(GALAXY_PROBE, timeout=timeout) as r:
            return 200 <= r.status < 500
    except Exception:  # noqa: BLE001 — any failure means "use git"
        return False


def plan() -> list[list[str]]:
    lock = yaml.safe_load(LOCK.read_text())
    src = yaml.safe_load(SOURCES.read_text())
    cmds: list[list[str]] = []
    missing: list[str] = []
    for c in lock.get("collections", []):
        row = src.get("collections", {}).get(c["name"])
        if not row:
            missing.append(c["name"])
            continue
        deps = row.get("deps") or []
        # --no-deps everywhere: a git install resolves galaxy.yml
        # `dependencies:` against Galaxy — the host we cannot reach. The lock
        # plus the `deps:` rows ARE the complete closure, installed explicitly.
        for d in deps:
            cmds.append(["ansible-galaxy", "collection", "install", "--no-deps",
                         f"git+{d['git']},{d['version']}"])
        cmds.append(["ansible-galaxy", "collection", "install", "--no-deps",
                     f"git+{row['git']},{c['version']}"])
    for r in lock.get("roles", []):
        row = src.get("roles", {}).get(r["name"])
        if not row:
            missing.append(r["name"])
            continue
        cmds.append(["ansible-galaxy", "role", "install",
                     f"git+{row['git']},{r['version']},{r['name']}"])
    if missing:
        sys.exit(f"[galaxy-install] no git source for: {', '.join(missing)} "
                 f"— add them to {SOURCES.relative_to(REPO)}")
    return cmds


def run(cmd: list[str]) -> None:
    for attempt in range(1, 4):
        p = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True)
        tail = (p.stdout + p.stderr).strip().splitlines()[-1:] or [""]
        if p.returncode == 0:
            print(f"[galaxy-install] {tail[0]}")
            return
        print(f"[galaxy-install] attempt {attempt} failed: {' '.join(cmd)}\n{p.stdout}{p.stderr}",
              file=sys.stderr)
    sys.exit(1)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", choices=["auto", "galaxy", "git"], default="auto")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--probe", action="store_true",
                    help="exit 0 when Galaxy answers, 1 when it does not")
    a = ap.parse_args()
    if a.probe:
        return 0 if galaxy_reachable() else 1

    source = a.source
    if source == "auto":
        source = "galaxy" if galaxy_reachable() else "git"
    print(f"[galaxy-install] source={source} ANSIBLE_HOME={os.environ.get('ANSIBLE_HOME', '<default>')}")

    if source == "galaxy":
        cmds = [["ansible-galaxy", "install", "-r", str(LOCK)]]
    else:
        cmds = plan()
    if a.check:
        for c in cmds:
            print("  " + " ".join(c))
        return 0
    for c in cmds:
        run(c)
    return 0


if __name__ == "__main__":
    sys.exit(main())
