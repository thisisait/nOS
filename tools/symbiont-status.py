#!/usr/bin/env python3
"""Where each symbiont keeps what: its mounts, and what it writes outside them (lost on recreate).

A symbiont is a running container (named by its compose service). For each one this reader lists every
bind and volume mount (source, destination, read-only, and the disk it lands on: a /Volumes/<name> path is
named by its volume) and counts the files `docker diff` reports changed outside those mounts (kinds A and C),
with the top 5 path prefixes. Every write outside a mount is lost when a converge recreates the container,
so it is flagged. Row symbiont-census-reader; the kind of symbiosis is row symbiont-census-kind.

Reads only: `docker ps`, `docker inspect`, `docker diff`, each with a timeout. Never exec, cp or rm; never
prints container env or labels wholesale (mount sources and paths only). An unreadable docker is UNKNOWN.
Exit 0 always.

Usage:
    tools/symbiont-status.py [--json] [--docker docker]
"""
from __future__ import annotations

import argparse
import collections
import json
import subprocess
import sys

#: Writes outside mounts the registry row tolerates, as path prefixes: cache paths for every symbiont, and
#: /tmp for paperclip only, until row symbiosome-tidy-paperclip lands (state/immune/indicators.yml).
TOLERATED = ("/home/node/.cache",)
TOLERATED_FOR = {"paperclip": ("/tmp",)}


def _run(args: list[str], timeout: int = 30) -> str | None:
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


def _disk(source: str) -> str:
    parts = source.split("/")
    if source.startswith("/Volumes/") and len(parts) > 2:
        return f"volume {parts[2]}"
    return "internal" if source.startswith("/") else "docker volume"


def _prefix(path: str, depth: int = 2) -> str:
    return "/" + "/".join([p for p in path.split("/") if p][:depth])


def symbiont(c: dict, docker: str) -> dict:
    labels = (c.get("Config") or {}).get("Labels") or {}
    name = labels.get("com.docker.compose.service") or (c.get("Name") or "").lstrip("/")
    mounts = [{"type": m.get("Type"), "source": m.get("Source") or m.get("Name") or "",
               "destination": m.get("Destination") or "", "read_only": not m.get("RW", True),
               "disk": _disk(m.get("Source") or "") if m.get("Type") == "bind" else "docker volume"}
              for m in c.get("Mounts") or []]
    dests = sorted((m["destination"].rstrip("/") for m in mounts if m["destination"]), key=len, reverse=True)
    raw = _run([docker, "diff", c.get("Id", "")], timeout=30)
    writes: dict = {"count": None, "top": [], "tolerated": 0}
    if raw is not None:
        outside = []
        for line in raw.splitlines():
            kind, _, path = line.partition(" ")
            if kind not in ("A", "C") or not path:
                continue
            if any(path == d or path.startswith(d + "/") for d in dests):
                continue
            outside.append(path)
        tol = TOLERATED + TOLERATED_FOR.get(name, ())
        kept = [p for p in outside if not any(p == t or p.startswith(t + "/") for t in tol)]
        # A changed directory and the files under it both appear; count the leaves only.
        leaves = [p for p in kept if not any(q != p and q.startswith(p + "/") for q in kept)]
        writes = {"count": len(leaves), "tolerated": len(outside) - len(kept),
                  "top": [f"{pfx} ({n})" for pfx, n in collections.Counter(_prefix(p.rsplit("/", 1)[0] or p) for p in leaves).most_common(5)]}
    return {"name": name, "image": (c.get("Config") or {}).get("Image"), "mounts": mounts,
            "writes_outside": writes, "lost_on_recreate": bool(writes["count"]),
            "recreated_by_converge": "/stacks/" in (labels.get("com.docker.compose.project.config_files") or "")}


def collect(docker: str = "docker") -> dict:
    ids = _run([docker, "ps", "-q"])
    if ids is None:
        return {"symbionts": [], "sources_missing": ["docker ps (no answer)"]}
    ids = ids.split()
    if not ids:
        return {"symbionts": [], "sources_missing": []}
    raw = _run([docker, "inspect", *ids], timeout=60)
    try:
        containers = json.loads(raw) if raw else None
    except ValueError:
        containers = None
    if containers is None:
        return {"symbionts": [], "sources_missing": ["docker inspect (no answer)"]}
    out = sorted((symbiont(c, docker) for c in containers), key=lambda s: s["name"])
    missing = [f"docker diff {s['name']}" for s in out if s["writes_outside"]["count"] is None]
    return {"symbionts": out, "sources_missing": missing}


def summary(report: dict) -> list[str]:
    if report["sources_missing"] and not report["symbionts"]:
        return [f"symbionts: UNKNOWN ({', '.join(report['sources_missing'])})"]
    lost = [s for s in report["symbionts"] if s["lost_on_recreate"]]
    lines = [f"symbionts: {len(report['symbionts'])} running, {len(lost)} write outside their mounts (lost on recreate)"]
    for s in report["symbionts"]:
        w = s["writes_outside"]
        state = "UNKNOWN" if w["count"] is None else (f"{w['count']} lost on recreate" if w["count"] else "all writes in mounts")
        lines.append(f"  {s['name']:28s} {len(s['mounts'])} mount(s) · {state}"
                     + (f" · top {', '.join(w['top'])}" if w.get("top") else "")
                     + (f" · {w['tolerated']} tolerated" if w.get("tolerated") else ""))
        for m in s["mounts"]:
            lines.append(f"      {m['destination']} <- {m['source']} [{m['disk']}{', ro' if m['read_only'] else ''}]")
    for miss in report["sources_missing"]:
        lines.append(f"  UNKNOWN: {miss}")
    return lines


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--docker", default="docker")
    args = ap.parse_args()
    report = collect(args.docker)
    if args.json:
        json.dump(report, sys.stdout, indent=1)
        print()
    else:
        print("\n".join(summary(report)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
