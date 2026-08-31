#!/usr/bin/env python3
"""Which running containers are serving config the estate has already replaced.

WHAT THIS CATCHES. Measured 2026-08-31: a Traefik scrape job was rendered into
`~/stacks/observability/prometheus/prometheus.yml` by a converge that finished
`failed=0`, and Prometheus never read it. Nothing in the estate makes a running
container re-read a mounted file: `docker compose up -d` is a no-op when the
service DEFINITION is unchanged, `/-/reload` is 403 because the lifecycle API is
off on purpose, and the plugin loader's job ends at the render. The edge target
stayed absent while every surface said the converge had succeeded.

It is not one service's bug. Fourteen plugins render config into a running
container this way — alloy, authentik, grafana and its five composition
plugins, loki, prometheus, tempo — and each one has the same gap between "the
repo says X" and "the process is running X".

WHY A READER AND NOT A HANDLER. A notify/handler pair only fires when the
playbook itself was the writer, on the run that wrote. It cannot see a config
that changed on a run whose restart failed, one a previous session left behind,
or a hand edit — and those are exactly the cases where a stale process survives
longest, because the converge that would have caught it already reported green.
Asking the artifact (file mtime vs the container's own StartedAt) answers for
every writer and at any later time.

READ-ONLY. Restarts nothing, exits 0 whatever it finds — a stale container is a
report, not this tool's decision. `tools/red-status.py` is the sibling shape.

  tools/stale-config-status.py            # human table
  tools/stale-config-status.py --json     # for a pane or a converge task
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import subprocess
import sys

#: A container may legitimately touch a mounted file after it starts (a lock, a
#: cache, a socket). Only READ-ONLY binds are candidates — an rw mount is the
#: container's own data.
GRACE_SECONDS = 5.0

#: ...and read-only is not enough on its own. Grafana mounts wing.db read-only
#: and reads it on every query; mcpo mounts a source tree read-only and reads it
#: per request. Neither is stale — they never cached anything to go stale.
#:
#: What distinguishes CONFIG is where it comes from: the estate renders config
#: into `stacks_dir`, and the 14 plugins that render into a running container
#: all target a path under it. Data lives elsewhere by convention — on the
#: external volume, in a named volume, or in an organ's own directory. So the
#: source path is the filter, and it is a filter on PROVENANCE rather than on
#: the shape of the file, which is why it does not need to guess.
#:
#: KNOWN FALSE POSITIVES, and why they are not filtered out. A process that
#: re-reads its mount without being restarted is reported here and is not
#: actually stale:
#:
#:   * nginx serving a rendered docroot (`iiab-apex-1`) re-reads per request.
#:   * authentik re-applies `/blueprints/custom` on a schedule. MEASURED
#:     2026-08-31, not assumed: the container had been up since 08-23 and
#:     `authentik_blueprints_blueprintinstance.last_applied` carried same-day
#:     timestamps for four blueprints.
#:
#: They stay in the report because the alternative is worse. An exclusion list
#: is a claim that a process re-reads its config, and a claim like that rots
#: silently — an upstream version that drops the watcher would turn the
#: exclusion into a blind spot exactly where a stale config now goes unnoticed
#: forever. What the tool KNOWS is "the file is newer than the process", which
#: is a fact; whether that matters is per-service knowledge, and it belongs in
#: the operator's head or in a follow-up, not in a filter that fails silently.
#:
#: ponytail: report-with-noise over filter-with-rot. Revisit if the noise ever
#: costs more than the two rows it is.
STACKS_DIR = pathlib.Path(
    os.environ.get("NOS_STACKS_DIR", pathlib.Path.home() / "stacks")).resolve()


def _newest_mtime(path: str) -> float | None:
    """Newest mtime under `path`, or None when it is not a readable file/dir.

    Directories matter as much as files: Prometheus mounts its whole `rules/`
    dir read-only, and a rule file added to it is exactly this defect.
    """
    p = pathlib.Path(path)
    try:
        if p.is_file():
            return p.stat().st_mtime
        if p.is_dir():
            newest = p.stat().st_mtime
            for child in p.rglob("*"):
                try:
                    newest = max(newest, child.stat().st_mtime)
                except OSError:
                    continue
            return newest
    except OSError:
        return None
    return None


def scan() -> dict:
    try:
        ids = subprocess.run(["docker", "ps", "-q"], capture_output=True,
                             text=True, timeout=30, check=True).stdout.split()
    except (OSError, subprocess.SubprocessError) as exc:
        # UNKNOWN, never green: an unreadable source is not an empty one.
        return {"readable": False, "error": str(exc), "containers": 0, "stale": []}
    if not ids:
        return {"readable": True, "containers": 0, "stale": []}
    try:
        raw = subprocess.run(["docker", "inspect", *ids], capture_output=True,
                             text=True, timeout=60, check=True).stdout
        containers = json.loads(raw)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return {"readable": False, "error": str(exc), "containers": 0, "stale": []}

    stale = []
    for c in containers:
        started_raw = c.get("State", {}).get("StartedAt", "")
        try:
            started = dt.datetime.fromisoformat(
                started_raw.replace("Z", "+00:00")).timestamp()
        except ValueError:
            continue
        for mount in c.get("Mounts", []):
            if mount.get("Type") != "bind" or mount.get("RW", True):
                continue
            try:
                source = pathlib.Path(mount.get("Source", "")).resolve()
            except OSError:
                continue
            if not source.is_relative_to(STACKS_DIR):
                continue
            mtime = _newest_mtime(mount.get("Source", ""))
            if mtime is None or mtime <= started + GRACE_SECONDS:
                continue
            stale.append({
                "container": c.get("Name", "").lstrip("/"),
                "source": mount["Source"],
                "destination": mount.get("Destination", ""),
                "config_written": dt.datetime.fromtimestamp(mtime).isoformat(timespec="seconds"),
                "process_started": dt.datetime.fromtimestamp(started).isoformat(timespec="seconds"),
                "stale_hours": round((mtime - started) / 3600, 2),
            })
    stale.sort(key=lambda r: -r["stale_hours"])
    return {"readable": True, "containers": len(containers), "stale": stale}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    report = scan()
    if args.json:
        json.dump(report, sys.stdout, indent=2)
        print()
        return 0

    if not report["readable"]:
        print(f"UNKNOWN — could not read docker: {report['error']}")
        return 0
    stale = report["stale"]
    print(f"{report['containers']} running containers · "
          f"{len(stale)} serving replaced config  (config under {STACKS_DIR})")
    if not stale:
        print("  every read-only mount is older than the process that read it.")
        return 0
    print()
    for row in stale:
        print(f"  {row['container']:34} {row['stale_hours']:>8.2f}h stale")
        print(f"      {row['source']} -> {row['destination']}")
        print(f"      written {row['config_written']}, running since {row['process_started']}")
    print("\n  Restart these to make the estate match the repo. This tool will not.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
