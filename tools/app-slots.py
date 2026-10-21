#!/usr/bin/env python3
"""Which app names, subdomains and host ports are taken here, and is one free.

READER. Sources: state/manifest.yml (service ids + domain_var/port_var resolved
through the config layers by nos_identity), apps/*.yml (+ drafts) and
roles/pazny.*, Traefik's rendered dynamic routes (~/stacks/infra/traefik/conf.d),
and with --live the host's listening TCP ports (netstat / ss, read-only).
A check is free: true only when every source it needs was read; a name a read
source holds is false; otherwise null. Exit 0 always.
Gate: tests/anatomy/test_app_slots_reader.py. Consumer: nos_app_parser --estate.

  tools/app-slots.py --json [--name N] [--subdomain S] [--port P]
                     [--free-port] [--from 8100] [--to 8999] [--live]
"""

from __future__ import annotations

import argparse
import json
import platform
import re
import subprocess
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nos_identity  # noqa: E402

# Which sources each check needs; listening joins port checks only with --live.
NEEDS = {"name": ("manifest", "apps"), "subdomain": ("manifest", "apps", "traefik"),
         "port": ("manifest", "apps")}
HOST_RE = re.compile(r"Host(?:SNI)?\(`([^`]+)`\)")


def _label(host: str) -> str:
    return str(host).split(".", 1)[0].lower()


def _manifest(names: dict, subs: dict, ports: dict) -> None:
    rows = nos_identity.services()
    wanted = [r[k] for r in rows for k in ("domain_var", "port_var") if r.get(k)]
    vals = nos_identity.resolved(wanted)
    for r in rows:
        sid = str(r.get("id") or "")
        if not sid:
            continue
        names.setdefault(sid.replace("_", "-"), f"state/manifest.yml service {sid}")
        dom = vals.get(r.get("domain_var") or "", "")
        if dom:
            subs.setdefault(_label(dom), f"state/manifest.yml {sid} ({dom})")
        try:
            ports.setdefault(int(vals.get(r.get("port_var") or "", "")), f"state/manifest.yml {sid}")
        except (TypeError, ValueError):
            pass


def _apps(names: dict, subs: dict, ports: dict) -> None:
    root = nos_identity.REPO
    for d in sorted((root / "roles").iterdir()):
        if d.name.startswith("pazny."):
            names.setdefault(d.name[6:].replace("_", "-"), f"roles/{d.name}")
    for p in sorted((root / "apps").glob("*.yml*")):
        if p.name.startswith("_"):
            continue
        rel = f"apps/{p.name}"
        doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        meta = doc.get("meta") or {}
        name = str(meta.get("name") or p.name.split(".", 1)[0])
        names.setdefault(name, rel)
        subs.setdefault(str((doc.get("nginx") or {}).get("subdomain") or name).lower(), rel)
        for port in meta.get("ports") or []:
            try:
                ports.setdefault(int(port), rel)
            except (TypeError, ValueError):
                pass
        for svc in ((doc.get("compose") or {}).get("services") or {}).values():
            for spec in (svc or {}).get("ports") or []:
                host = spec.get("published") if isinstance(spec, dict) \
                    else str(spec).split("/", 1)[0].rpartition(":")[0].rpartition(":")[2]
                try:
                    ports.setdefault(int(host), rel)
                except (TypeError, ValueError):
                    pass


def _traefik(subs: dict) -> None:
    conf = Path.home() / "stacks" / "infra" / "traefik" / "conf.d"
    files = sorted(conf.glob("*.yml"))
    if not files:
        raise FileNotFoundError(f"no route files in {conf}")
    for f in files:
        for host in HOST_RE.findall(f.read_text(encoding="utf-8")):
            subs.setdefault(_label(host), f"traefik route {host}")


def _listening(ports: dict) -> None:
    if platform.system() == "Darwin":  # netstat sees every user's sockets, lsof only ours
        out = subprocess.run(["netstat", "-an", "-p", "tcp"], capture_output=True, text=True,
                             timeout=10, check=True).stdout
        addrs = [ln.split()[3] for ln in out.splitlines() if ln.endswith("LISTEN") and len(ln.split()) > 3]
        sep = "."
    else:
        out = subprocess.run(["ss", "-ltnH"], capture_output=True, text=True, timeout=10, check=True).stdout
        addrs = [ln.split()[3] for ln in out.splitlines() if len(ln.split()) > 3]
        sep = ":"
    for a in addrs:
        try:
            ports.setdefault(int(a.rsplit(sep, 1)[1]), f"listening on {a}")
        except (IndexError, ValueError):
            pass


def collect(args) -> dict:
    names: dict = {}
    subs: dict = {}
    ports: dict = {}
    sources: dict = {}
    steps = [("manifest", lambda: _manifest(names, subs, ports)), ("apps", lambda: _apps(names, subs, ports)),
             ("traefik", lambda: _traefik(subs))]
    if args.live:
        steps.append(("listening", lambda: _listening(ports)))
    for src, fn in steps:
        try:
            fn()
            sources[src] = "ok"
        except Exception as e:  # noqa: BLE001 — a reader names it, never dies on it
            sources[src] = f"UNKNOWN: {type(e).__name__}: {e}"
    unknown = [f"{k}: {v[len('UNKNOWN: '):]}" for k, v in sources.items() if v != "ok"]

    def needs(kind):
        return NEEDS[kind] + (("listening",) if kind == "port" and args.live else ())

    def check(kind, value, taken):
        hit = taken.get(value)
        missing = [s for s in needs(kind) if sources.get(s) != "ok"]
        if hit:
            return {"value": value, "free": False, "why": f"taken: {hit}"}
        if missing:
            return {"value": value, "free": None, "why": "UNKNOWN: " + "; ".join(f"{s} {sources[s]}" for s in missing)}
        return {"value": value, "free": True, "why": "free in " + ", ".join(needs(kind))}

    checks = {}
    if args.name is not None:
        checks["name"] = check("name", args.name, names)
    if args.subdomain is not None:
        checks["subdomain"] = check("subdomain", args.subdomain.lower(), subs)
    if args.port is not None:
        checks["port"] = check("port", args.port, ports)
    free_port = None
    if args.free_port and all(sources.get(s) == "ok" for s in needs("port")):
        free_port = next((p for p in range(args.from_, args.to + 1) if p not in ports), None)
    return {"names_taken": sorted(names), "subdomains_taken": sorted(subs), "ports_taken": sorted(ports),
            "checks": checks, "free_port": free_port, "sources": sources, "unknown": unknown}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--name")
    ap.add_argument("--subdomain")
    ap.add_argument("--port", type=int)
    ap.add_argument("--free-port", action="store_true")
    ap.add_argument("--from", dest="from_", type=int, default=8100)
    ap.add_argument("--to", type=int, default=8999)
    ap.add_argument("--live", action="store_true")
    args = ap.parse_args()
    out = collect(args)
    if args.json:
        print(json.dumps(out))
        return 0
    for kind, c in out["checks"].items():
        state = {True: "free", False: "TAKEN", None: "UNKNOWN"}[c["free"]]
        print(f"{kind:<10} {c['value']!s:<24} {state:<8} {c['why']}")
    if args.free_port:
        print(f"free_port  {out['free_port']}")
    print(f"taken: {len(out['names_taken'])} names, {len(out['subdomains_taken'])} subdomains, "
          f"{len(out['ports_taken'])} ports")
    for u in out["unknown"]:
        print(f"UNKNOWN: {u}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
