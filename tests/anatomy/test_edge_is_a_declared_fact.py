"""Anatomy gate — how clients reach the host (`nos_edge`) is one declared fact.

`cloudflare`: a public zone that Cloudflare may front (origin-pull door allowed,
ACME through `acme_dns_provider`). `lan_tailscale`: no public IP; dnsmasq answers
the LAN IP on the LAN and over the tailnet, and the Cloudflare door is refused.
Edge study 2026-10-06, roadmap rows edge-tld-class / edge-declared-fact.
"""
from __future__ import annotations

import sys
from pathlib import Path

import jinja2
import pytest
import yaml

from test_origin_pull_is_a_second_door import SERVICES, render  # type: ignore

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import nos_identity as ni  # noqa: E402

EDGES = ("cloudflare", "lan_tailscale")
ENV = jinja2.Environment(undefined=jinja2.ChainableUndefined)
ENV.filters.update(bool=lambda v: v.strip().lower() in ("true", "1", "yes") if isinstance(v, str) else bool(v),
                   combine=lambda a, b: {**a, **b})


def _true(exprs, **ctx) -> bool:
    exprs = exprs if isinstance(exprs, list) else [exprs]
    return all(ENV.from_string("{{ " + str(e) + " }}").render(ctx) == "True" for e in exprs)


def _main_tasks():
    play = yaml.safe_load((REPO / "main.yml").read_text())[0]
    return [t for s in ("pre_tasks", "tasks", "post_tasks") for t in play.get(s) or []]


def _task(tasks, needle):
    return next(t for t in tasks if needle in str(t.get("name", "")) or needle == t.get("import_tasks"))


# ── declared once, and the operator's estate does not move ──────────────────
def test_declared_once_and_derived_from_the_tld():
    defaults = {str(p.relative_to(REPO)) for p in ni.default_layers()}
    declared = [layer for layer, _ in ni.resolve_flag("nos_edge") if layer != "config.yml"]
    assert len(declared) == 1 and declared[0] in defaults, declared
    expr = ni.default_config()["nos_edge"]
    assert ENV.from_string(expr).render(tenant_domain_is_local=False) == "cloudflare"   # pazny.eu today
    assert ENV.from_string(expr).render(tenant_domain_is_local=True) == "lan_tailscale"


# ── (a) the Cloudflare origin-pull door ─────────────────────────────────────
@pytest.mark.parametrize("edge", EDGES)
def test_origin_twin_renders_only_for_cloudflare(edge):
    routers = yaml.safe_load(render(SERVICES, traefik_origin_pull_enabled=True, nos_edge=edge))["http"]["routers"]
    twins = [n for n in routers if n.endswith("-origin")]
    assert bool(twins) is (edge == "cloudflare"), f"{edge}: {len(twins)} origin twins"


@pytest.mark.parametrize("edge, origin_pull, refused", [
    ("lan_tailscale", True, True), ("lan_tailscale", False, False),
    ("cloudflare", True, False), ("cloudflare", False, False),
])
def test_lan_tailscale_refuses_origin_pull(edge, origin_pull, refused):
    t = _task(_main_tasks(), "Refuse Cloudflare origin-pull")
    assert "ansible.builtin.fail" in t and "preflight" in t["tags"]
    assert _true(t["when"], nos_edge=edge, traefik_origin_pull_enabled=origin_pull) is refused


@pytest.mark.parametrize("edge, refused", [("cloudflare", False), ("lan_tailscale", False), ("cloudfare", True)])
def test_an_unknown_edge_is_refused(edge, refused):
    t = _task(_main_tasks(), "nos_edge must be")
    assert _true(t["when"], nos_edge=edge) is refused


# ── (b) dnsmasq answers on the LAN, even for a public domain ────────────────
@pytest.mark.parametrize("edge, runs", [("cloudflare", False), ("lan_tailscale", True)])
def test_dnsmasq_runs_and_listens_on_the_lan(edge, runs):
    ctx = dict(nos_edge=edge, tenant_domain_is_local=False, dnsmasq_force_local_domains=False,
               install_dnsmasq=True, dnsmasq_lan_access=False)
    assert _true(_task(_main_tasks(), "tasks/dnsmasq.yml")["when"], **ctx) is runs
    dns = yaml.safe_load((REPO / "tasks/dnsmasq.yml").read_text())
    lan = next(t for t in dns if "_dnsmasq_lan" in (t.get("ansible.builtin.set_fact") or {}))
    assert _true(lan["ansible.builtin.set_fact"]["_dnsmasq_lan"].strip("{} "), **ctx) is runs
    listen = _task(dns, "Build listen addresses")["ansible.builtin.set_fact"]["_dnsmasq_listen"]
    assert ("192.168.1.10" in ENV.from_string(listen).render(_dnsmasq_lan=runs, nos_lan_ip="192.168.1.10")) is runs


# ── (c) certificates: acme.sh's own --dns contract, not a hardcoded Cloudflare ─
def test_acme_dns_provider_is_a_variable():
    acme = yaml.safe_load((REPO / "roles/pazny.acme/tasks/main.yml").read_text())
    issue = _task(acme, "Issue/renew wildcard cert")
    cmd = issue["ansible.builtin.command"]
    assert "dns_cf" not in cmd and "--dns {{ acme_dns_provider }}" in cmd
    assert ni.default_config()["acme_dns_provider"] == "dns_cf"    # nothing changes for the operator
    env = ENV.from_string(issue["environment"]).render(
        acme_cloudflare_api_token="cf", acme_dns_env={"HETZNER_TOKEN": "h"}, ansible_facts={"env": {"HOME": "/h"}})
    assert yaml.safe_load(env) == {"CF_Token": "cf", "HOME": "/h", "HETZNER_TOKEN": "h"}
    # The nightly renewal (acme.sh --cron) needs the same credentials.
    plist = ENV.from_string((REPO / "roles/pazny.acme/templates/acme-renew.plist.j2").read_text()).render(
        acme_cloudflare_api_token="cf", acme_dns_env={"HETZNER_TOKEN": "h"}, ansible_facts={"env": {"HOME": "/h"}})
    assert "<key>HETZNER_TOKEN</key>" in plist and "<string>h</string>" in plist
