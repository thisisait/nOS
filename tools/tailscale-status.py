#!/usr/bin/env python3
"""Can the tailnet reach nOS by name (nos_edge: lan_tailscale)?

Reads `tailscale status --json`, `tailscale debug prefs`, `tailscale serve status
--json` and one `dig @<nos_lan_ip>` probe, and reports installed, up, hostname,
the /32 route advertised vs approved, LAN DNS, and Funnel (must be off) — each
OK / RED / UNKNOWN with its source. Steps: docs/systems/tailscale/README.md.

Reads only. Exit 0 always. A source it cannot read is UNKNOWN, never green. It
cannot see the tailnet's split-DNS setting (that needs an API key nOS refuses).

Usage: tools/tailscale-status.py [--json]
Env (tests): NOS_TAILSCALE_BIN, NOS_LAN_IP, NOS_TENANT_DOMAIN, NOS_EDGE.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nos_identity as ni  # noqa: E402

OK, RED, UNKNOWN = "OK", "RED", "UNKNOWN"
CANDIDATES = ("/opt/homebrew/bin/tailscale", "/usr/local/bin/tailscale", "/Applications/Tailscale.app/Contents/MacOS/Tailscale")


def declared(name: str) -> str | None:
    """The last layer's literal; a Jinja value is not guessed."""
    seen = ni.resolve_flag(name)
    value = seen[-1][1] if seen else None
    return None if value is None or "{{" in value else value


def lan_ip() -> tuple[str | None, str]:
    """nos_lan_ip as declared, else the default-route source address (what Ansible's default_ipv4 reports)."""
    if v := os.environ.get("NOS_LAN_IP") or declared("nos_lan_ip"):
        return v, "nos_lan_ip"
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 53))      # no packet is sent: UDP connect only picks a route
            return s.getsockname()[0], "default route"
    except OSError:
        return None, "default route"


def run(argv: list[str]) -> str | None:
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=8)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


def as_json(text: str | None) -> dict | None:
    try:
        return json.loads(text) if text and text.strip() else ({} if text is not None else None)
    except ValueError:
        return None


def judge(status: dict | None, prefs: dict | None, serve: dict | None, dig: str | None,
          ip: str | None, domain: str | None, edge: str | None, binary: str | None) -> list[dict]:
    L = lambda c, s, d, src: {"check": c, "state": s, "detail": d, "source": src}  # noqa: E731
    if not binary:
        return [L("installed", UNKNOWN, "no tailscale CLI found; nothing else was read", "PATH + " + ", ".join(CANDIDATES))]
    out = [L("installed", OK, binary, "PATH")]
    if status is None:
        return out + [L("up", UNKNOWN, "tailscale status unreadable", "tailscale status --json")]
    state = status.get("BackendState", "?")
    out.append(L("up", OK if state == "Running" else RED, state, "tailscale status --json"))
    me = status.get("Self") or {}
    out.append(L("hostname", OK if me.get("HostName") else UNKNOWN, f"{me.get('HostName')} ({me.get('DNSName')})", "Self"))
    lan = edge == "lan_tailscale"
    route = f"{ip}/32" if ip else None
    adv = (prefs or {}).get("AdvertiseRoutes") or []
    approved = me.get("PrimaryRoutes") or []
    if not lan:
        out.append(L("route", OK, f"nos_edge is {edge}: no route expected", "nos_edge"))
    elif prefs is None or not route:
        out.append(L("route", UNKNOWN, "advertised routes or nos_lan_ip unreadable", "tailscale debug prefs"))
    else:
        s = OK if route in adv and route in approved else RED
        out.append(L("route", s, f"{route}: advertised={route in adv} approved={route in approved}"
                     + ("" if route in approved else " (admin console → Machines → Edit route settings)"), "prefs + Self.PrimaryRoutes"))
    if lan:
        if dig is None or not ip or not domain:
            out.append(L("lan dns", UNKNOWN, "dig, nos_lan_ip or tenant_domain unavailable", "dig"))
        else:
            out.append(L("lan dns", OK if ip in dig.split() else RED, f"@{ip} grafana.{domain} → {dig.split() or 'no answer'}", "dig"))
    if serve is None:
        out.append(L("funnel", UNKNOWN, "serve status unreadable", "tailscale serve status --json"))
    else:
        on = serve.get("AllowFunnel") or {}
        out.append(L("funnel", RED if on else OK, f"public on {sorted(on)}" if on else "off", "tailscale serve status --json"))
    return out


def collect() -> list[dict]:
    pinned = os.environ.get("NOS_TAILSCALE_BIN")
    binary = ((pinned if os.access(pinned, os.X_OK) else None) if pinned is not None
              else shutil.which("tailscale") or next((c for c in CANDIDATES if os.access(c, os.X_OK)), None))
    domain = os.environ.get("NOS_TENANT_DOMAIN") or declared("tenant_domain")
    edge = os.environ.get("NOS_EDGE") or declared("nos_edge") or (
        ("lan_tailscale" if ni.is_local_domain(domain) else "cloudflare") if domain else None)
    ip, _ = lan_ip()
    if not binary:
        return judge(None, None, None, None, ip, domain, edge, None)
    q = lambda *a: as_json(run([binary, *a]))  # noqa: E731
    dig = run(["dig", "+short", "+time=2", "+tries=1", f"@{ip}", f"grafana.{domain}"]) if ip and domain and edge == "lan_tailscale" else None
    return judge(q("status", "--json"), q("debug", "prefs"), q("serve", "status", "--json"), dig, ip, domain, edge, binary)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    lines = collect()
    if ap.parse_args().json:
        print(json.dumps(lines, indent=1))
        return 0
    for ln in lines:
        print(f"{ln['state']:8} {ln['check']:10} {ln['detail']}   [{ln['source']}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
