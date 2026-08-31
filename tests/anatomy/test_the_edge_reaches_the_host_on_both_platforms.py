"""Traefik's route to a host daemon must not be a macOS address on Linux.

`roles/pazny.traefik/templates/dynamic/services.yml.j2` routes the host-daemon
services — wing, openclaw, hermes — at `traefik_host_gateway_ip`. Its literal
default is `192.168.65.254`, which is Docker DESKTOP's gateway: a macOS address
that was hardcoded as the default for every platform, with a comment inviting a
per-host override that a Linux install had no reason to know about.

MEASURED IN CI 2026-08-31, on the first run where Linux had a Traefik at all:
every router answered a uniform 500 — face, wing, mailpit and all four Tier-2
apps — because that IP does not exist on a Linux bridge network. The defect is
as old as the Linux port. Nothing could see it because CI ran `install_traefik:
false`, so there was no edge to fail (docs/hidden_fees/39).

WHAT THIS PINS. That the default is RESOLVED per platform rather than being one
literal. It cannot check reachability — that needs a live Docker on each OS and
belongs to the CI wet-test, which is precisely the thing that just found it.
"""

from __future__ import annotations

import pathlib
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
PLATFORM = ROOT / "tasks/_platform.yml"
SERVICES = ROOT / "roles/pazny.traefik/templates/dynamic/services.yml.j2"

#: The Docker Desktop (macOS) gateway. Correct there, meaningless on Linux.
MAC_GATEWAY = "192.168.65.254"


def _platform_tasks() -> list[dict]:
    return [t for t in yaml.safe_load(PLATFORM.read_text(encoding="utf-8")) or []
            if isinstance(t, dict)]


def test_the_gateway_is_resolved_per_platform() -> None:
    setters = [t for t in _platform_tasks()
               if "traefik_host_gateway_ip" in str(t.get("ansible.builtin.set_fact")
                                                   or t.get("set_fact") or "")]
    assert setters, (
        "tasks/_platform.yml no longer resolves traefik_host_gateway_ip. Without "
        f"it the value falls back to the literal {MAC_GATEWAY} in "
        "services.yml.j2 — Docker Desktop's gateway — and every host-daemon "
        "route on Linux answers 500.")

    body = yaml.dump(setters)
    assert "macos" in body, (
        "the resolver does not branch on platform, so it is a second hardcoded "
        "default rather than a fix")
    assert MAC_GATEWAY in body, (
        f"the macOS branch no longer carries {MAC_GATEWAY}. services.yml.j2 "
        "records that the IPv6 `nos-host` alias does NOT reach host loopback on "
        "macOS, so that literal is a measurement, not an arbitrary choice")


def test_the_template_still_defers_to_the_variable() -> None:
    """The resolver is pointless if the template stops reading the variable."""
    body = SERVICES.read_text(encoding="utf-8")
    assert "traefik_host_gateway_ip" in body, (
        "services.yml.j2 no longer reads traefik_host_gateway_ip — the platform "
        "resolution in tasks/_platform.yml now governs nothing")
