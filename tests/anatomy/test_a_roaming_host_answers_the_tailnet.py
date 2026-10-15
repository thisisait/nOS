"""A roaming Mac answers *.<tenant_domain> with 127.0.0.1 on loopback only, so the
person's phone on the tailnet could not reach it by name (operator 2026-10-15).
A second dnsmasq listens on the Tailscale address alone and answers that address;
it exists only while roaming with a Tailscale IP, and every removal takes it."""
from __future__ import annotations

import importlib.util
import plistlib
import re
import sys
from pathlib import Path

import jinja2
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
ENV = jinja2.Environment()
ENV.filters["bool"] = lambda v: v.strip().lower() in ("true", "1", "yes") if isinstance(v, str) else bool(v)
TS_IP = "100.101.102.103"
LABEL = "eu.thisisait.nos.dnsmasq-tailnet"
PLIST = f"/Library/LaunchDaemons/{LABEL}.plist"
CONF = "/opt/homebrew/etc/dnsmasq-tailnet.conf"


def _tasks() -> dict:
    return {t["name"]: t for t in yaml.safe_load((REPO / "tasks/dnsmasq.yml").read_text())}


def _render(expr: str, **v) -> str:
    return ENV.from_string(expr).render(**v).strip()


def _decide(roaming: bool, raw: dict, os_family: str = "Darwin") -> dict:
    f = _tasks()["[dnsmasq] Tailnet: decide"]["ansible.builtin.set_fact"]
    ip = _render(f["_dnsmasq_ts_ip"], _dnsmasq_ts_raw=raw)
    on = _render(f["_dnsmasq_tailnet"], _dnsmasq_ts_ip=ip, nos_lan_roaming=roaming, ansible_os_family=os_family)
    return {"ip": ip, "on": on == "True"}


def _when(name: str, **v) -> bool:
    w = _tasks()[name]["when"]
    expr = " and ".join(f"({c})" for c in (w if isinstance(w, list) else [w]))
    return _render("{{ " + expr + " }}", **v) == "True"


UP = {"rc": 0, "stdout": TS_IP + "\n"}
DOWN = {"rc": 1, "stdout": ""}


def test_the_instance_is_on_only_when_roaming_with_a_tailscale_ip():
    assert _decide(True, UP) == {"ip": TS_IP, "on": True}
    assert _decide(True, DOWN) == {"ip": "", "on": False}
    assert _decide(True, {"rc": 0, "stdout": "Tailscale is stopped."}) == {"ip": "", "on": False}
    assert _decide(False, UP)["on"] is False
    assert _decide(True, UP, "Debian")["on"] is False


def test_install_tasks_run_only_when_on_and_removal_only_when_not_roaming():
    for name in ("[dnsmasq] Tailnet: render the config", "[dnsmasq] Tailnet: install the LaunchDaemon",
                 "[dnsmasq] Tailnet: load it"):
        assert _when(name, _dnsmasq_tailnet=True, nos_lan_roaming=True) is True, name
        assert _when(name, _dnsmasq_tailnet=False, nos_lan_roaming=True) is False, name
    gone = "[dnsmasq] Tailnet: remove it when not roaming"
    assert _when(gone, nos_lan_roaming=False) is True
    assert _when(gone, nos_lan_roaming=True) is False


def test_the_config_answers_the_tailscale_ip_and_never_loopback():
    conf = _render((REPO / "templates/dnsmasq-tailnet.conf.j2").read_text(),
                   _dnsmasq_ts_ip=TS_IP, dnsmasq_dev_domain="office.lan")
    lines = {ln.strip() for ln in conf.splitlines() if ln.strip() and not ln.startswith("#")}
    assert {f"listen-address={TS_IP}", "bind-interfaces", f"address=/.office.lan/{TS_IP}",
            "local=/office.lan/", "no-resolv"} <= lines
    assert "127.0.0.1" not in conf and not any(ln.startswith("interface=") for ln in lines)


def test_the_launchdaemon_retries_its_own_config():
    plist = plistlib.loads(_render((REPO / f"templates/{LABEL}.plist.j2").read_text(),
                                   homebrew_prefix="/opt/homebrew", dnsmasq_tailnet_conf=CONF).encode())
    assert plist["Label"] == LABEL and plist["KeepAlive"] is True and plist["ThrottleInterval"] > 0
    args = plist["ProgramArguments"]
    assert args[args.index("-C") + 1] == CONF and "--keep-in-foreground" in args


def test_every_removal_takes_both_files():
    spec = importlib.util.spec_from_file_location("managed_status", REPO / "tools/managed-status.py")
    ms = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ms)
    env = ms.jinja()
    data, _all, _keep = ms.removal_levels(env, ms.config_ctx(env))
    assert {PLIST, CONF} <= data, "remove=data (and so every level) must remove the tailnet plist + config"
    stop = next(t for t in yaml.safe_load((REPO / "tasks/blank-reset.yml").read_text())
                if t.get("name") == "[BLANK] Stop Homebrew services (direct launchctl)")
    assert f"launchctl bootout system/{LABEL}" in stop["ansible.builtin.shell"], "booted out before its plist goes"


def test_the_verify_digs_the_tailscale_ip_and_is_unknown_without_one():
    t = _tasks()
    ask = t["[dnsmasq] Tailnet verify: ask it"]
    assert "verify" in ask["tags"] and "@{{ _dnsmasq_ts_ip }}" in ask["ansible.builtin.command"]["argv"]
    unknown = t["[dnsmasq] Tailnet verify: UNKNOWN without a Tailscale IP"]
    assert "verify" in unknown["tags"] and "failed_when" not in unknown
    assert _when(unknown.get("name"), nos_lan_roaming=True, _dnsmasq_tailnet=False) is True


def test_traefik_publishes_443_on_every_interface():
    src = (REPO / "roles/pazny.traefik/templates/compose.yml.j2").read_text()
    line = next(m for m in re.findall(r'-\s*"([^"]*:443)"', src))
    assert _render(line) == "443:443", f"a host IP on the 443 mapping hides Traefik from the tailnet: {line}"
