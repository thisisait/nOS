"""Every name the plan promises resolves on THIS host, through the system resolver.

The journeys need DNS first; nos-smoke retries a gaierror against loopback,
which hid a host that could not resolve its own names (the mini, 14/20 red).
This probe has no fallback: a name the resolver does not answer is red here,
one line per name, before any journey blames SSO for it.
"""
from __future__ import annotations

import ipaddress
import os
import socket

import pytest

from conftest import _plan_module
from nos_identity import is_local_host

PM = _plan_module()
try:
    PLAN = PM.plan()
except Exception as exc:  # noqa: BLE001
    PLAN, _PLAN_ERROR = [], exc
NAMES = sorted({PM._host(s["launch_url"]) for s in PLAN if s.get("launch_url")} - {""})


def _lan_ip() -> str | None:
    """nos_lan_ip comes from facts at converge; offline, NOS_LAN_IP or nothing."""
    raw = os.environ.get("NOS_LAN_IP") or str(PM.smoke.load_vars().get("nos_lan_ip") or "")
    try:
        return str(ipaddress.IPv4Address(raw))
    except ValueError:
        return None


ALLOWED = {"127.0.0.1"} | ({ip} if (ip := _lan_ip()) else set())


def test_the_plan_names_hosts():
    assert NAMES, f"tools/e2e-plan.py produced no launch hosts ({globals().get('_PLAN_ERROR')})"


@pytest.mark.parametrize("name", NAMES)
def test_name_resolves(name):
    try:
        addrs = {ai[4][0] for ai in socket.getaddrinfo(name, 443, socket.AF_INET, socket.SOCK_STREAM)}
    except socket.gaierror as exc:
        pytest.fail(f"{name}: the system resolver does not answer ({exc})")
    if not is_local_host(name):
        return      # a public name answers the public edge; that it resolves is the verdict
    assert addrs & ALLOWED, f"{name} resolves to {sorted(addrs)}, not this host ({sorted(ALLOWED)})"
