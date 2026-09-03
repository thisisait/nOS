#!/usr/bin/env python3
"""What nOS knows about its WAN router, and what it can actually measure.

WHY THIS EXISTS. The estate sits behind a Mercusys BE3600 (MR27BE), a
login-walled consumer router with no documented API — see
docs/router-as-estate-fact.md. Everything about it (model, admin URL, the
declared port-forward list, whether remote management/UPnP are supposed to be
off) was a sentence in an ADR checklist until now. This reader turns the
declared half into something `tools/red-status.py`-style tooling can ask, and
is honest about the other half: nOS cannot log into the router, so it cannot
confirm the forwards or the remote-mgmt/UPnP toggles actually match what was
declared. It only checks that the gateway answers at all.

WHAT IT IS NOT. Not a scraper of the router's admin UI (fragile foreign
surface, no credentials stored, no API to scrape anyway). Not a WAN-side
reachability check — a container cannot self-probe its own edge from inside;
that evidence lives in the Traefik/edge-log reader instead. Not a config
pusher. Read-only, no network beyond one HTTP request to the LAN gateway.

Exit 0 always, matching every other *-status.py reader here — this reports,
it does not gate.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import urllib.request

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
ROUTER_YML = REPO / "state" / "router.yml"


def load_declared() -> dict | None:
    if not ROUTER_YML.exists():
        return None
    return yaml.safe_load(ROUTER_YML.read_text()).get("router")


def probe_gateway(url: str, timeout: float = 5.0) -> str:
    """Presence only. 'reachable' / 'unreachable' — never a health verdict,
    because a 200 from a login page says nothing about the router's config."""
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=timeout):
            return "reachable"
    except Exception:
        return "unreachable"


def collect() -> dict:
    declared = load_declared()
    if declared is None:
        return {"status": "UNKNOWN", "reason": f"{ROUTER_YML} not found"}

    gateway_status = probe_gateway(declared.get("admin_url", ""))
    firmware = declared.get("firmware", {})
    stale_firmware_note = (
        "operator has never recorded a firmware check"
        if firmware.get("checked_on") in (None, "TODO")
        else None
    )

    return {
        "status": "OK" if gateway_status == "reachable" else "UNKNOWN",
        "model": declared.get("model"),
        "gateway_ip": declared.get("gateway_ip"),
        "gateway_probe": gateway_status,
        "firmware_declared": firmware,
        "firmware_note": stale_firmware_note,
        "declared_config": declared.get("declared"),
        "measured_config": None,  # no credentialed path exists — see docstring
        "note": (
            "forwards/remote-mgmt/UPnP are DECLARED (operator intent), not "
            "measured — this router has no unauthenticated status API"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report = collect()

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    if report["status"] == "UNKNOWN" and "reason" in report:
        print(f"router: UNKNOWN — {report['reason']}")
        return 0

    print(f"router: {report['model']} @ {report['gateway_ip']}")
    print(f"  gateway probe : {report['gateway_probe']} ({report['status']})")
    fw = report["firmware_declared"]
    print(f"  firmware      : {fw.get('version')} (checked {fw.get('checked_on')})")
    if report["firmware_note"]:
        print(f"  note          : {report['firmware_note']}")
    dc = report["declared_config"] or {}
    print(f"  declared      : remote_mgmt={dc.get('remote_management_enabled')} "
          f"upnp={dc.get('upnp_enabled')} "
          f"forwards={[f['port'] for f in dc.get('port_forwards', [])]}")
    print("  measured      : none — no unauthenticated router API exists "
          "(see docs/router-as-estate-fact.md)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
