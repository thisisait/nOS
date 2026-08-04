#!/usr/bin/env python3
"""Cross-check every installed npm package against a published IOC list.

WHY THIS EXISTS
---------------
On 2026-08-04 the ChainDrop worm compromised 443 npm packages and 2 235
versions in under four hours, starting from `keyv@6.0.0` (153.7M weekly
downloads) and spreading through harvested maintainer credentials. Its dropper
runs as an INSTALL LIFECYCLE SCRIPT and its payload harvests npm, GitHub, AWS,
Vault, Kubernetes and SSH credentials — and specifically `.claude/credentials
.json` — then plants persistence in `.claude/settings.json` SessionStart hooks.

This estate was clean when checked that evening (6 315 package.json scanned,
0 of 2 235 malicious versions present) but only because eslint pins
keyv/flat-cache/file-entry-cache below the poisoned majors. That is semver
luck, and luck does not repeat on request.

WHAT THIS DOES AND DOES NOT CLAIM
---------------------------------
It answers exactly one question: *is a known-bad name@version installed here?*

It does NOT detect an unknown compromise, a poisoned version not yet on the
list, or a payload already executed and cleaned up. A clean result means "none
of the currently-published indicators are present", and the tool says so in
those words rather than "clean" — the difference is the whole lesson of
2026-08-04, when a container reported healthy for ten days while serving its
own installer.

WHY THE LIST IS FETCHED, NOT VENDORED
-------------------------------------
A vendored copy is a snapshot of what was known on the day it was committed,
and this list grew while the worm was still running. A stale IOC list that
reports "no indicators" is worse than no scan, so a fetch failure is an ERROR
(exit 2), never a silent pass. `--offline` with `--list` is available for an
air-gapped run, and it labels its own output as point-in-time.

Usage
-----
  npm-ioc-scan.py [--roots DIR ...] [--list URL|PATH] [--offline] [--json]

Exit codes
----------
  0  scanned; no listed indicator present
  1  AT LEAST ONE compromised name@version is installed
  2  could not obtain the IOC list, or no roots were scanned (nothing proven)
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
import urllib.request
from pathlib import Path

DEFAULT_LIST = (
    "https://raw.githubusercontent.com/wiz-sec-public/wiz-research-iocs/"
    "main/reports/keyv-packages.csv"
)

# Where npm packages actually live on this estate. `~` is expanded per-run.
DEFAULT_ROOTS = [
    "~/.nvm/versions/node",
    "~/projects/nOS",
    "~/keap",
    "~/wing",
    "~/.bun",
]

# Filesystem indicators from the StepSecurity write-up. Presence is not proof,
# absence is not safety — but each one is cheap and specific.
FS_INDICATORS = [
    ("~/.local/bin/gh-token-monitor.sh", "worm token-revocation trigger"),
    ("~/.claude/settings.json", "check for SessionStart hooks you did not add"),
]


def fetch_list(source: str, offline: bool) -> str:
    """Return the raw CSV text, or raise. Never returns partial data."""
    if os.path.exists(source):
        return Path(source).read_text(encoding="utf-8")
    if offline:
        raise RuntimeError(f"--offline given but {source} is not a local file")
    with urllib.request.urlopen(source, timeout=60) as resp:  # noqa: S310
        if resp.status != 200:
            raise RuntimeError(f"{source} returned HTTP {resp.status}")
        return resp.read().decode("utf-8")


def parse_list(text: str) -> dict[str, set[str]]:
    """package -> {malicious versions}. Tolerates ranges written as a list."""
    ioc: dict[str, set[str]] = {}
    for row in csv.DictReader(io.StringIO(text)):
        pkg = (row.get("Package") or "").strip()
        if not pkg:
            continue
        raw = (row.get("Malicious Versions") or "").replace('"', "")
        ioc.setdefault(pkg, set()).update(
            v.strip() for v in raw.split(",") if v.strip()
        )
    return ioc


def installed_packages(roots: list[Path]) -> dict[tuple[str, str], list[str]]:
    """Every name@version with a package.json under any root."""
    found: dict[tuple[str, str], list[str]] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for dirpath, _dirnames, filenames in os.walk(root, followlinks=False):
            if "package.json" not in filenames:
                continue
            p = Path(dirpath) / "package.json"
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            name, version = data.get("name"), data.get("version")
            if name:
                found.setdefault((name, version), []).append(str(p))
    return found


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--roots", nargs="*", default=DEFAULT_ROOTS)
    ap.add_argument("--list", default=DEFAULT_LIST,
                    help="IOC CSV: a URL, or a local path for --offline")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    try:
        ioc = parse_list(fetch_list(args.list, args.offline))
    except Exception as exc:
        # Exit 2, loudly. A scan that could not read its list has proven
        # NOTHING, and reporting that as "no indicators found" is the exact
        # defect this estate keeps finding in its own gates.
        print(f"[-] could not obtain the IOC list: {exc}", file=sys.stderr)
        print("[-] NOTHING WAS CHECKED. This is not a clean result.",
              file=sys.stderr)
        return 2

    roots = [Path(r).expanduser() for r in args.roots]
    present = [r for r in roots if r.is_dir()]
    if not present:
        print(f"[-] none of the roots exist: {args.roots}", file=sys.stderr)
        print("[-] NOTHING WAS CHECKED.", file=sys.stderr)
        return 2

    found = installed_packages(present)
    name_hits = [(n, v, paths) for (n, v), paths in found.items() if n in ioc]
    exact = [(n, v, paths) for n, v, paths in name_hits if v in ioc[n]]

    result = {
        "ioc_packages": len(ioc),
        "ioc_versions": sum(len(v) for v in ioc.values()),
        "roots_scanned": [str(r) for r in present],
        "manifests_scanned": len(found),
        "name_matches": [
            {"name": n, "installed": v, "malicious": sorted(ioc[n]),
             "locations": len(paths)}
            for n, v, paths in sorted(name_hits)
        ],
        "compromised": [
            {"name": n, "version": v, "locations": paths}
            for n, v, paths in sorted(exact)
        ],
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"IOC list: {result['ioc_packages']} packages / "
              f"{result['ioc_versions']} malicious versions")
        print(f"scanned : {result['manifests_scanned']} distinct name@version "
              f"across {len(present)} root(s)")
        for m in result["name_matches"]:
            mark = "COMPROMISED" if m["installed"] in m["malicious"] else "clean"
            print(f"  {m['name']}@{m['installed']}  [{mark}]  "
                  f"malicious: {', '.join(m['malicious'][:4])}"
                  f"{'…' if len(m['malicious']) > 4 else ''}  "
                  f"({m['locations']} location(s))")
        for c in result["compromised"]:
            print(f"  !! {c['name']}@{c['version']}")
            for loc in c["locations"]:
                print(f"       {loc}")
        # Deliberately not the word "clean".
        print("\n" + ("COMPROMISED PACKAGES PRESENT" if exact else
                      "No listed indicator present. This does NOT rule out an "
                      "unlisted or already-cleaned compromise."))

        for rel, why in FS_INDICATORS:
            p = Path(rel).expanduser()
            if p.exists():
                print(f"  [i] {p} exists — {why}")

    return 1 if exact else 0


if __name__ == "__main__":
    sys.exit(main())
