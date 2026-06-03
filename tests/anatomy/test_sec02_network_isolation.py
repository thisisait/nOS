"""Anatomy gate (SEC-02) — calibre-web + 2FAuth isolated on the Traefik-only gated_net.

These header-trust backends blindly trust the forwarded X-authentik-* identity
header (zero validation upstream), so a peer container on the flat shared_net could
forge it direct to the backend. Fix: put them on a Traefik-only `gated_net` (off
shared_net / stack nets) so only Traefik reaches them. Pins the wiring so it can't
silently regress back onto shared_net.

CI-safe: source/YAML scan; no Docker.
"""
from __future__ import annotations

import pathlib
import re

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
CALIBRE = REPO / "roles/pazny.calibre_web/templates/compose.yml.j2"
TWOFAUTH = REPO / "apps/twofauth.yml"
TRAEFIK_DEFAULTS = REPO / "roles/pazny.traefik/defaults/main.yml"
SHARED_NET = REPO / "tasks/stacks/shared-network.yml"


def _service_networks(template_text: str) -> list[str]:
    """The `- <name>` items under the FIRST service-level `networks:` block."""
    m = re.search(r"\n    networks:\n((?:\s*#.*\n|\s*-\s*\S+\n)+)", template_text)
    assert m, "no service networks: block found"
    return re.findall(r"^\s*-\s+(\S+)", m.group(1), re.M)


def test_calibre_on_gated_net_only():
    items = _service_networks(CALIBRE.read_text())
    assert items == ["gated_net"], (
        f"calibre-web must join ONLY gated_net (off iiab_net/shared_net), got {items}"
    )


def test_twofauth_on_gated_net_only():
    d = yaml.safe_load(TWOFAUTH.read_text())
    nets = (((d.get("compose") or {}).get("services") or {}).get("twofauth") or {}).get("networks")
    assert nets == ["gated_net"], f"2FAuth must declare networks: [gated_net], got {nets!r}"


def test_traefik_joins_both_gated_nets():
    d = yaml.safe_load(TRAEFIK_DEFAULTS.read_text())
    nets = d.get("traefik_networks") or []
    assert "gated_net" in nets and "gated_b2b_net" in nets, (
        f"Traefik must join both gated nets to route the isolated backends, got {nets}"
    )


def test_shared_network_task_creates_gated_nets():
    t = SHARED_NET.read_text()
    assert "gated_net" in t and "gated_b2b_net" in t and "network create" in t, (
        "shared-network.yml must pre-create gated_net + gated_b2b_net (external)"
    )
