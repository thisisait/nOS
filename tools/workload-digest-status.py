#!/usr/bin/env python3
"""Did any container's image change since the last converge recorded it?

Roadmap `digest-drift-red`. Most images here are unsigned and several are built
locally, so per-role digest pins would be costly and partial. Instead the
converge records what each container runs (`tools/workload-digest-record.py` →
`~/.nos/workload-digests.json`) and this reader compares the live estate
against that record:

  DRIFT       same container name, different image ID than recorded — the
              image changed without a converge (watchtower in apply mode, a
              hand `docker pull && up`, a rebuild outside nOS). RED.
  UNRECORDED  running, but the last converge did not see it (info)
  GONE        recorded, not running now (info)

A missing or torn record, or docker unreachable, is UNKNOWN, never green.
It reads only: `docker inspect` with a format string, never Config.Env.

Usage: tools/workload-digest-status.py [--json]. Exit 0 always.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys

RECORD = pathlib.Path(os.environ.get(
    "NOS_WORKLOAD_DIGESTS", str(pathlib.Path.home() / ".nos" / "workload-digests.json")))
TIMEOUT = 30
#: Only these fields leave docker — the container env carries secrets.
_CFMT = '{{.Name}}\t{{.Image}}\t{{.Config.Image}}'
_IFMT = '{{.Id}}\t{{json .RepoDigests}}'


def _docker(*args: str) -> str | None:
    docker = shutil.which("docker")
    if not docker:
        return None
    try:
        p = subprocess.run([docker, *args], capture_output=True, text=True, timeout=TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None
    return p.stdout if p.returncode == 0 else None


def snapshot() -> dict | None:
    """name -> {image, image_id, repo_digests, source: None}; None = cannot ask.

    A container that exits between `ps` and `inspect` fails the whole inspect
    (short-lived Pulse/backup runs); one retry takes a fresh `ps`."""
    return _snapshot() or _snapshot()


def _snapshot() -> dict | None:
    ids = _docker("ps", "-q", "--no-trunc")
    if ids is None:
        return None
    ids = ids.split()
    if not ids:
        return {}
    text = _docker("inspect", "--format", _CFMT, *ids)
    if text is None:
        return None
    rows = [ln.split("\t") for ln in text.splitlines() if ln.count("\t") == 2]
    image_ids = sorted({r[1] for r in rows})
    digests: dict[str, list] = {}
    itext = _docker("image", "inspect", "--format", _IFMT, *image_ids) if image_ids else ""
    for ln in (itext or "").splitlines():
        iid, _, raw = ln.partition("\t")
        try:
            digests[iid] = json.loads(raw) or []
        except ValueError:
            digests[iid] = []
    return {name.lstrip("/"): {"image": ref, "image_id": iid,
                               "repo_digests": digests.get(iid, []), "source": None}
            for name, iid, ref in rows}


def compare(record: dict, live: dict) -> dict:
    recorded = record.get("containers") or {}
    drift, ok = [], 0
    for name in sorted(set(recorded) & set(live)):
        was, now = recorded[name], live[name]
        if was.get("image_id") == now.get("image_id"):
            ok += 1
            continue
        drift.append({"container": name, "image": now.get("image"),
                      "recorded_image": was.get("image"),
                      "recorded_id": was.get("image_id"), "live_id": now.get("image_id"),
                      "recorded_source": was.get("source")})
    return {"recorded_at": record.get("recorded_at"), "drift": drift, "ok": ok,
            "unrecorded": sorted(set(live) - set(recorded)),
            "gone": sorted(set(recorded) - set(live))}


def collect(path: pathlib.Path = RECORD, live: dict | None = None) -> dict:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(record.get("containers"), dict):
            raise ValueError("no containers map")
    except (OSError, ValueError, AttributeError) as exc:
        return {"unknown": f"record {path} unreadable ({exc}) — a converge writes it"}
    if live is None:
        live = snapshot()
    if live is None:
        return {"unknown": "docker unreachable — cannot read what runs"}
    return compare(record, live)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    report = collect()
    if args.json:
        json.dump(report, sys.stdout, indent=2)
        print()
        return 0
    if "unknown" in report:
        print(f"UNKNOWN: {report['unknown']}")
        return 0
    print(f"recorded by the converge at {report['recorded_at']}: "
          f"{report['ok']} unchanged, {len(report['drift'])} DRIFT")
    for d in report["drift"]:
        src = (d.get("recorded_source") or {}).get("commit")
        print(f"  DRIFT {d['container']}: {d['recorded_image']} {d['recorded_id'][:19]} "
              f"-> {d['image']} {d['live_id'][:19]}" + (f" (built from {src[:12]})" if src else ""))
    for label in ("unrecorded", "gone"):
        if report[label]:
            print(f"  {label} ({len(report[label])}): {', '.join(report[label])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
