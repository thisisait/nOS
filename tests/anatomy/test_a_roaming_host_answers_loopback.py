"""A host that leaves its office LAN (a client takes the Mac home) must keep reaching
itself by name. lan_tailscale bakes nos_lan_ip into dnsmasq at converge time, so a new
DHCP address left *.<tenant_domain> pointing at the old office IP (client, 2026-10-15).
nos_lan_roaming: dnsmasq answers 127.0.0.1 and listens on loopback only, and the
tailnet advertises no LAN route (reach the host by its Tailscale address instead)."""
from __future__ import annotations

from pathlib import Path

import jinja2
import yaml

REPO = Path(__file__).resolve().parents[2]
ENV = jinja2.Environment()
ENV.filters["bool"] = lambda v: v.strip().lower() in ("true", "1", "yes") if isinstance(v, str) else bool(v)


def _facts(path: str, name: str) -> dict:
    task = next(t for t in yaml.safe_load((REPO / path).read_text()) if t.get("name") == name)
    return task["ansible.builtin.set_fact"]


def _render(expr: str, **v) -> str:
    return ENV.from_string(expr).render(**v).strip()


def _dnsmasq(roaming: bool) -> dict:
    lan = _render(_facts("tasks/dnsmasq.yml", "[dnsmasq] Decide whether to answer on the LAN")["_dnsmasq_lan"],
                  dnsmasq_lan_access=True, nos_edge="lan_tailscale", nos_lan_roaming=roaming) == "True"
    f = _facts("tasks/dnsmasq.yml", "[dnsmasq] Build listen addresses")
    return {k: _render(f[k], nos_lan_ip="192.168.1.197", _dnsmasq_lan=lan) for k in ("_dnsmasq_listen", "_dnsmasq_target")}


def test_an_office_host_answers_its_lan_address():
    assert _dnsmasq(False) == {"_dnsmasq_listen": "127.0.0.1,192.168.1.197", "_dnsmasq_target": "192.168.1.197"}


def test_a_roaming_host_answers_loopback_and_listens_on_loopback_only():
    assert _dnsmasq(True) == {"_dnsmasq_listen": "127.0.0.1", "_dnsmasq_target": "127.0.0.1"}


def test_a_roaming_host_advertises_no_lan_route():
    expr = _facts("tasks/tailscale.yml", "[Tailscale] Name the CLI and the route")["_ts_lan"]
    assert _render(expr, nos_edge="lan_tailscale", nos_lan_roaming=False) == "True"
    assert _render(expr, nos_edge="lan_tailscale", nos_lan_roaming=True) == "False"


def test_roaming_is_declared_off_by_default():
    assert yaml.safe_load((REPO / "default.config.yml").read_text())["nos_lan_roaming"] is False
