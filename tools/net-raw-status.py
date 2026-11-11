#!/usr/bin/env python3
"""Which running containers still hold NET_RAW — the effect check for cap_drop (row net-raw-drop-audit).

WHY. NET_RAW lets a process forge packets and sniff on its network: an ARP or DNS spoof from any
compromised container on a shared Docker network. sec-transport-enforce drops it in the compose
templates; this reads what Docker actually runs (HostConfig.CapDrop / CapAdd / Privileged), so a
template that says cap_drop but a container created before it is still counted. A reader: it acts
on nothing, exits 0, and reports an unreadable docker as UNKNOWN, never as clean.

Usage:
    tools/net-raw-status.py [--json] [--selftest]
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location("container_status", Path(__file__).with_name("container-status.py"))
_cs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_cs)

DROPS = {"NET_RAW", "CAP_NET_RAW", "ALL", "CAP_ALL"}


def holds(c: dict) -> str | None:
    """Why a container holds NET_RAW, or None when it is dropped."""
    hc = c.get("HostConfig") or {}
    if hc.get("Privileged"):
        return "privileged"
    added = {str(x).upper() for x in hc.get("CapAdd") or []}
    if added & {"NET_RAW", "CAP_NET_RAW", "ALL", "CAP_ALL"}:
        return "cap_add"
    if not ({str(x).upper() for x in hc.get("CapDrop") or []} & DROPS):
        return "not dropped"
    return None


def collect(containers: list[dict] | None) -> dict:
    if containers is None:
        return {"status": "UNKNOWN", "why": "docker inspect unreadable", "holding": [], "dropped": 0}
    running = [c for c in containers if (c.get("State") or {}).get("Running")]
    holding = [{"name": (c.get("Name") or "?").lstrip("/"), "why": w} for c in running if (w := holds(c))]
    return {"status": "holding" if holding else "ok", "holding": sorted(holding, key=lambda h: h["name"]),
            "dropped": len(running) - len(holding), "running": len(running)}


def selftest() -> int:
    c = lambda name, **hc: {"Name": "/" + name, "State": {"Running": True}, "HostConfig": hc}  # noqa: E731
    r = collect([c("a", CapDrop=["NET_RAW"]), c("b"), c("c", CapDrop=["ALL"], CapAdd=["NET_RAW"]),
                 c("d", Privileged=True, CapDrop=["ALL"]), c("e", CapDrop=["cap_net_raw"]),
                 {"Name": "/f", "State": {"Running": False}, "HostConfig": {}}])
    assert r["status"] == "holding" and r["dropped"] == 2 and r["running"] == 5, r
    assert [(h["name"], h["why"]) for h in r["holding"]] == [("b", "not dropped"), ("c", "cap_add"), ("d", "privileged")], r
    assert collect([])["status"] == "ok"
    assert collect(None)["status"] == "UNKNOWN"
    print("selftest OK: dropped / not dropped / cap_add / privileged / stopped / UNKNOWN")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    r = collect(_cs.inspect())
    if a.json:
        print(json.dumps(r, indent=2))
        return 0
    if r["status"] == "UNKNOWN":
        print(f"NET_RAW: UNKNOWN — {r['why']}")
        return 0
    print(f"NET_RAW: {r['dropped']}/{r['running']} running containers drop it")
    for h in r["holding"]:
        print(f"  holds  {h['name']:<40} {h['why']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
