#!/usr/bin/env python3
"""Sanction a symbiont: cut its supply through its symbiosome, reversibly, data untouched.

The immune system's first quarantine effector (ssot/doctrine/immune-system.md §4:
report is the default; anything stronger is operator consent, dry-run first). The
patrol or the operator names the symbiont; nothing here is armed by a model.

  edge   its Traefik routers answer 403 to every caller: middleware sanction-<router>@file
         (on every router, rendered open by pazny.traefik) narrows to 127.0.0.1/32.
         Traefik watches conf.d, so the cut is live within a second.
  stop   edge, plus its compose containers stopped; volumes untouched. A port it
         publishes on the LAN (Jellyfin 8096) is only closed by stop.

The record is ~/.nos/sanctions.yml; the converge renders the same cut from it, so a
converge never lifts a sanction. Lift restores the open range and starts what stop stopped.

  tools/nos-sanction.py --list
  tools/nos-sanction.py jellyfin --level edge --reason "GHSA-6828 critical"   # plan only
  tools/nos-sanction.py jellyfin --level edge --reason "..." --confirm
  tools/nos-sanction.py jellyfin --lift --confirm
"""
from __future__ import annotations

import argparse
import os
import pathlib
import subprocess
import sys
from datetime import datetime, timezone

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import nos_identity as ni  # noqa: E402

RECORD = pathlib.Path(os.environ.get("NOS_SANCTIONS_FILE") or pathlib.Path.home() / ".nos" / "sanctions.yml")
CUT = ["127.0.0.1/32"]
OPEN = ["0.0.0.0/0", "::/0"]
LEVELS = ("edge", "stop")


def dynamic_file() -> pathlib.Path:
    stacks = pathlib.Path(os.environ.get("NOS_STACKS_DIR") or pathlib.Path.home() / "stacks")
    return stacks / "infra" / "traefik" / "conf.d" / "sanctions.yml"


def router(sid: str) -> str:
    return sid.replace("_", "-")


def load_record() -> dict:
    doc = yaml.safe_load(RECORD.read_text(encoding="utf-8")) if RECORD.is_file() else None
    return (doc or {}).get("sanctions") or {}


def write_record(sanctions: dict) -> None:
    RECORD.parent.mkdir(parents=True, exist_ok=True)
    tmp = RECORD.with_suffix(".tmp")
    tmp.write_text("# Written by tools/nos-sanction.py; read by pazny.traefik and red-status.\n"
                   + yaml.safe_dump({"sanctions": sanctions}, sort_keys=True), encoding="utf-8")
    os.replace(tmp, RECORD)


def apply_edge(sid: str, cut: bool) -> str:
    """Flip one middleware in the rendered conf.d/sanctions.yml; refuse if it is not there."""
    f = dynamic_file()
    doc = yaml.safe_load(f.read_text(encoding="utf-8")) if f.is_file() else None
    mw = ((doc or {}).get("http") or {}).get("middlewares") or {}
    name = f"sanction-{router(sid)}"
    if name not in mw:
        raise SystemExit(f"{f} has no {name}: converge traefik first (nos --tags traefik); nothing changed")
    mw[name] = {"ipAllowList": {"sourceRange": CUT if cut else OPEN}}
    tmp = f.with_suffix(".tmp")
    tmp.write_text(yaml.safe_dump(doc, sort_keys=True), encoding="utf-8")
    os.replace(tmp, f)
    return f"{name}: {'cut' if cut else 'open'}"


def containers(sid: str) -> list[str]:
    out = []
    for svc in sorted({sid, router(sid)}):
        r = subprocess.run(["docker", "ps", "-a", "--filter", f"label=com.docker.compose.service={svc}",
                            "--format", "{{.Names}}"], capture_output=True, text=True, timeout=30)
        out += [n for n in r.stdout.split() if n]
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("id", nargs="?", help="manifest row id (jellyfin, rustfs, ...)")
    ap.add_argument("--level", choices=LEVELS, default="edge")
    ap.add_argument("--reason", default="")
    ap.add_argument("--lift", action="store_true")
    ap.add_argument("--confirm", action="store_true")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args(argv)
    sanctions = load_record()
    if a.list or not a.id:
        for sid, s in sorted(sanctions.items()):
            print(f"{sid:16} {s['level']:5} since {s['at']}  {s.get('reason', '')}")
        print(f"{len(sanctions)} sanction(s) in force ({RECORD})")
        return 0
    ids = {r["id"] for r in ni.services()}
    if a.id not in ids:
        print(f"{a.id}: not a manifest row id", file=sys.stderr)
        return 2
    if not a.lift and not a.reason:
        print("a sanction needs --reason (the advisory id, or why)", file=sys.stderr)
        return 2
    prior = sanctions.get(a.id)
    level = prior["level"] if a.lift and prior else a.level
    stop = level == "stop"
    plan = [f"traefik: sanction-{router(a.id)}@file -> {'open' if a.lift else 'cut (403)'}"]
    if stop:
        plan += [f"docker {'start' if a.lift else 'stop'} {c}" for c in containers(a.id)] or ["no container found"]
    plan.append(f"record: {RECORD} {'drops' if a.lift else 'holds'} {a.id}")
    print(("LIFT " if a.lift else f"SANCTION ({level}) ") + a.id + ("" if a.confirm else "  — plan only, add --confirm"))
    for step in plan:
        print("  " + step)
    if not a.confirm:
        return 0
    if a.lift:
        if not prior:
            print(f"{a.id} is not sanctioned")
            return 0
        print("  " + apply_edge(a.id, cut=False))
        for c in containers(a.id) if stop else []:
            subprocess.run(["docker", "start", c], check=True, capture_output=True, timeout=120)
        sanctions.pop(a.id)
    else:
        sanctions[a.id] = {"level": level, "reason": a.reason, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        write_record(sanctions)  # before the cut: a converge mid-way renders it cut, never open
        print("  " + apply_edge(a.id, cut=True))
        for c in containers(a.id) if stop else []:
            subprocess.run(["docker", "stop", c], check=True, capture_output=True, timeout=120)
    write_record(sanctions)
    return 0


if __name__ == "__main__":
    sys.exit(main())
