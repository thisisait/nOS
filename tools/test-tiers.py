#!/usr/bin/env python3
"""Which CI tier owns each anatomy test, and which bonus converge lane each stack gets.

Derived, never hand-listed: core = the install_* flags profiles/core.yml turns on, every
host row (no `stack:`) and every own organ (software_owner: self, ruling 2026-10-15). Each other manifest `stack:` is one bonus lane: its rows'
install flags and the paths that should trigger it (roles/pazny.<id>/ and every plugin dir
whose requires.feature_flag is one of those flags). A test file is T0 when its name says
security/secret/contract/lockfile/gitleaks, a lane when it names only that lane's flags,
roles or plugins, else core. Ownership only: the sharded pytest lane still runs every test.

Usage:
    tools/test-tiers.py                         # the whole derivation, JSON
    tools/test-tiers.py --select < changed-paths.txt         # matrix of lanes those paths touch
    tools/test-tiers.py --select --nightly [--day N]           # tonight's rotation (0=Monday)
"""
from __future__ import annotations

import argparse
import functools
import json
import pathlib
import re
import sys
from datetime import datetime, timezone

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
ALWAYS = re.compile(r"secur|secret|contract|lockfile|gitleak")


def _load(rel: str):
    return yaml.safe_load((REPO / rel).read_text(encoding="utf-8")) or {}


def core_flags() -> set[str]:
    return {k for k, v in _load("profiles/core.yml").items() if k.startswith("install_") and v is True}


@functools.cache
def derive() -> dict:
    core = core_flags()
    rows = _load("state/manifest.yml")["services"]
    flag_stacks: dict[str, set] = {}
    for r in rows:
        if r.get("stack") and r.get("install_flag") not in core and r.get("software_owner") != "self":
            flag_stacks.setdefault(r["install_flag"], set()).add(r["stack"])
    flag_tier = {f: next(iter(s)) if len(s) == 1 else "core" for f, s in flag_stacks.items()}
    lanes: dict[str, dict] = {}
    token_tier: dict[str, str] = {}
    for r in rows:
        tier = flag_tier.get(r.get("install_flag"), "core")
        token_tier[r["install_flag"]] = flag_tier.get(r["install_flag"], "core")
        token_tier[f"pazny.{r['id']}"] = tier
        if tier != "core":
            lane = lanes.setdefault(tier, {"flags": set(), "paths": set()})
            lane["flags"].add(r["install_flag"])
            if (REPO / "roles" / f"pazny.{r['id']}").is_dir():
                lane["paths"].add(f"roles/pazny.{r['id']}/")
    for plugin in sorted((REPO / "files/anatomy/plugins").glob("*/plugin.yml")):
        flag = ((yaml.safe_load(plugin.read_text(encoding="utf-8")) or {}).get("requires") or {}).get("feature_flag")
        if not flag:
            continue
        tier = flag_tier.get(flag, "core")
        token_tier[plugin.parent.name] = tier
        if tier != "core":
            lanes[tier]["paths"].add(f"files/anatomy/plugins/{plugin.parent.name}/")
    token = re.compile(r"(?<![\w.-])(" + "|".join(map(re.escape, sorted(token_tier, key=len, reverse=True))) + r")(?![\w-])")
    tests = {}
    for path in sorted((REPO / "tests/anatomy").glob("test_*.py")):
        named = {token_tier[m] for m in token.findall(path.read_text(encoding="utf-8", errors="replace"))}
        tests[path.name] = ("T0" if ALWAYS.search(path.name)
                            else named.pop() if len(named) == 1 and "core" not in named else "core")
    return {"lanes": {k: {"flags": sorted(v["flags"]), "paths": sorted(v["paths"])} for k, v in sorted(lanes.items())},
            "tests": tests}


def _entries(names) -> list[dict]:
    lanes = derive()["lanes"]
    return [{"stack": n, "flags": json.dumps({f: True for f in lanes[n]["flags"]})} for n in names]


def select(changed: list[str]) -> list[dict]:
    lanes = derive()["lanes"]
    return _entries(n for n, v in lanes.items() if any(c.startswith(tuple(v["paths"])) for c in changed))


def nightly(day: int) -> list[dict]:
    # 7 nights, each lane once a week; tools/ci-tier-status.py reds a lane not green in 7 days.
    return _entries(n for i, n in enumerate(derive()["lanes"]) if i % 7 == day % 7)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--select", action="store_true", help="print the lane matrix (JSON) for paths on stdin")
    ap.add_argument("--nightly", action="store_true", help="with --select: tonight's rotation instead of stdin")
    ap.add_argument("--day", type=int, default=datetime.now(timezone.utc).weekday())
    a = ap.parse_args()
    if not a.select:
        print(json.dumps(derive(), indent=1))
    elif a.nightly:
        print(json.dumps(nightly(a.day)))
    else:
        print(json.dumps(select([line.strip() for line in sys.stdin if line.strip()])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
