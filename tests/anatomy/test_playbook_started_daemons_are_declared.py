"""Anatomy CI gate — a daemon the converge starts is on the declared roster.

MEASURED 2026-10-04, first run of tools/undeclared-status.py: the converge
starts ai.openclaw.gateway (`openclaw gateway install`), sh.brew.grafana-alloy
and the root homebrew.mxcl.dnsmasq, but the anatomy-graph roster only knew
`eu.thisisait.nos.*`, so the reader called them undeclared and an install_*:
false never booted them out. Each label is declared ONCE as a
`*_launchd_label` var the starting task uses; the roster, the bootout plan and
the reader all derive from that. A root LaunchDaemon cannot be reached from
gui/<uid>: it carries its domain and is booted out with become, outside the
sudo-free stack layer.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import re

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
GRAPH = REPO / "state" / "anatomy-graph.json"

#: label -> (install flag, launchd domain, declaring var, files that must use it)
STARTED = {
    "ai.openclaw.gateway": ("install_openclaw", "gui", "openclaw_gateway_launchd_label",
                            ["roles/pazny.openclaw/tasks/main.yml"]),
    "com.ollama.agent": ("install_openclaw", "gui", "ollama_launchd_label",
                         ["roles/pazny.openclaw/tasks/main.yml",
                          "roles/pazny.openclaw/templates/ollama-agent.plist.j2"]),
    "sh.brew.grafana-alloy": ("install_observability", "gui", "observability_launchd_label",
                              ["main.yml"]),
    "homebrew.mxcl.dnsmasq": ("install_dnsmasq", "system", "dnsmasq_launchd_label",
                              ["tasks/dnsmasq.yml", "main.yml"]),
}


def _load(path: pathlib.Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _guard():
    return _load(REPO / "filter_plugins" / "nos_prune_guard.py", "_pg_started")


def _graph() -> dict:
    return json.loads(GRAPH.read_text(encoding="utf-8"))


def test_the_reader_names_none_of_the_playbook_started_set():
    mod = _load(REPO / "tools" / "undeclared-status.py", "_undecl_started")
    plists = {lbl: {"path": f"/x/{lbl}.plist", "program": "/p"} for lbl in STARTED}
    rows = mod.judge_launchd({lbl: 1 for lbl in STARTED}, plists, mod.declared_labels())
    assert not rows, f"still undeclared: {[r['label'] for r in rows]}"


def test_each_is_joined_to_its_install_flag_and_domain():
    plan = {r["label"]: (r["install_flag"], r["domain"])
            for r in _guard().nos_host_daemon_plan(_graph())}
    for label, (flag, domain, _var, _files) in STARTED.items():
        assert plan.get(label) == (flag, domain), (
            f"{label}: plan says {plan.get(label)}, the task that starts it is gated on {flag} "
            f"in the {domain} domain")


def test_a_gui_plan_cannot_reach_a_root_daemon():
    gui = {r["label"] for r in _guard().nos_host_daemon_plan(_graph(), "gui")}
    system = {r["label"] for r in _guard().nos_host_daemon_plan(_graph(), "system")}
    assert "homebrew.mxcl.dnsmasq" in system and "homebrew.mxcl.dnsmasq" not in gui
    assert "ai.openclaw.gateway" in gui and "ai.openclaw.gateway" not in system


def test_the_declared_label_is_the_one_the_starting_task_uses():
    for label, (_flag, _domain, var, files) in STARTED.items():
        for rel in files:
            text = (REPO / rel).read_text(encoding="utf-8")
            assert re.search(r"\{\{\s*" + var + r"\b", text), f"{rel} does not use {var}"
            assert label not in text, f"{rel} spells {label} literally — a second declaration"


def test_the_stack_layer_bootout_is_gui_only_and_system_has_become():
    prune = yaml.safe_load((REPO / "tasks/stacks/prune-disabled.yml").read_text(encoding="utf-8"))
    plan_calls = [str(t.get("ansible.builtin.set_fact")) for t in prune
                  if "nos_host_daemon_plan" in str(t.get("ansible.builtin.set_fact"))]
    assert plan_calls and all("nos_host_daemon_plan('gui')" in c for c in plan_calls), (
        "the sudo-free stack layer asks for every domain; gui/<uid> cannot boot out a root daemon")
    assert not any(t.get("become") for t in prune), "the stack layer must stay sudo-free (nos-stacks.sh)"
    play = yaml.safe_load((REPO / "main.yml").read_text(encoding="utf-8"))
    tasks = [t for p in play for t in (p.get("tasks") or [])]
    system = [t for t in tasks if "nos_host_daemon_plan('system')" in str(t)]
    boot = [t for t in system if "bootout" in str(t.get("ansible.builtin.command") or t.get("ansible.builtin.shell"))]
    assert boot and boot[0].get("become") is True, (
        "no become-d `launchctl bootout system/<label>` for a declared-off root daemon")


def test_a_root_daemons_listener_is_declared_by_its_program():
    """dnsmasq answers on LAN :53; a user `launchctl list` has no pid for a
    system-domain daemon, so the reader joins by the declared plist's program."""
    mod = _load(REPO / "tools" / "undeclared-status.py", "_undecl_ports")
    exe = "/opt/homebrew/opt/dnsmasq/sbin/dnsmasq"
    rows = [{"addr": "192.168.1.64", "port": 53, "pid": 9, "ppid": 1, "exe": exe}]
    assert mod.judge_ports(rows, set(), set()), "fixture must be undeclared without the join"
    assert not mod.judge_ports(rows, set(), set(), frozenset({exe}))
