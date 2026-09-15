"""Anatomy CI gate — a service that is off is stopped; only deletion is gated.

MEASURED 2026-09-02 by a reboot. `install_gitlab: false` sat in config.yml and
GitLab came back, because the only enforcement was bundled behind the deletion
flag and that flag was off. `restart: unless-stopped` resurrects anything the
converge did not stop.

The split:

    off at run time        docker stop            reversible   no gate, every converge
    deliberate removal     fragment + rm -f       permanent    uninstall_disabled_services

`unless-stopped` is what makes the safe half durable: an explicitly stopped
container stays stopped across a reboot, so no new machinery is needed.

CONFIRMED 2026-09-02 (operator ruling): the stop half is deliberately ungated
even for run-time disables (-e @profiles/...) — a profile is always an operator
act, and stop is reversible. Authored-only discipline applies to DELETION only.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
TASK = REPO / "tasks" / "stacks" / "prune-disabled.yml"
FILTER = REPO / "filter_plugins" / "nos_prune_guard.py"
CONFIG = REPO / "default.config.yml"
GRAPH = REPO / "state" / "anatomy-graph.json"
GATE = "uninstall_disabled_services"
BACKREST = "eu.thisisait.nos.backrest"


def _tasks() -> list[dict]:
    return yaml.safe_load(TASK.read_text(encoding="utf-8")) or []


def _argv(t: dict) -> list:
    return (t.get("ansible.builtin.command") or {}).get("argv") or []


def _plan():
    spec = importlib.util.spec_from_file_location("prune_guard", FILTER)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["prune_guard"] = mod
    spec.loader.exec_module(mod)
    return mod.nos_prune_plan


def test_the_stop_is_not_gated():
    stop = [t for t in _tasks() if "stop" in [str(a) for a in _argv(t)]]
    assert stop, (
        "nothing runs `docker stop` for a service that is off. Then a "
        "declaration in config.yml is enforced by nothing and a reboot "
        "resurrects it — the 2026-09-02 GitLab case")
    when = str(stop[0].get("when", ""))
    assert GATE not in when, (
        f"the stop is gated on {GATE}. Stopping is reversible and survives a "
        f"reboot; putting it behind the deletion flag is what left the "
        f"declaration unenforced")


def test_deletion_stays_gated():
    tasks = _tasks()
    rm_file = [t for t in tasks
               if (t.get("ansible.builtin.file") or {}).get("state") == "absent"]
    rm_ctr = [t for t in tasks if "rm" in [str(a) for a in _argv(t)]]
    assert rm_file and rm_ctr, "the deletion half is gone entirely"
    for t in rm_file + rm_ctr:
        assert GATE in str(t.get("when", "")), (
            f"a deletion task is not gated on {GATE}: {t.get('name')!r}. "
            f"Deleting a compose fragment is irreversible by a converge")


def test_the_stop_set_survives_a_refusal():
    """The refusal guards DELETION. An un-authored disablement must still stop
    its containers — otherwise a profile run enforces nothing, which is the
    state this change ends."""
    plan = _plan()
    ov = {"/s/b2b/overrides/onlyoffice.yml": ["onlyoffice"]}
    r = plan(["onlyoffice"], {"install_onlyoffice": True}, ov, ["b2b-onlyoffice-1"])
    assert r["unauthored_destructive"] == ["onlyoffice"], "the refusal is gone"
    assert r["fragments"] == [] and r["containers"] == [], (
        "a refused plan still offers something to delete")
    assert r["stop"] == ["b2b-onlyoffice-1"], (
        "the refusal also suppressed the stop set. Stopping is safe and must "
        "happen even when deletion is refused")


def test_the_retired_flag_is_refused_not_ignored():
    """A rename that silently drops the operator's setting is worse than the
    ambiguity it replaced."""
    tasks = _tasks()
    legacy = [t for t in tasks
              if "prune_disabled_overrides is defined" in str(t.get("when", ""))]
    assert legacy, (
        "nothing refuses a config.yml still carrying prune_disabled_overrides. "
        "It would be read by nobody and the operator would never know")
    assert "ansible.builtin.fail" in legacy[0], "the legacy check does not refuse"


def test_the_flag_is_declared_and_defaults_to_false():
    cfg = CONFIG.read_text(encoding="utf-8")
    m = re.search(rf"^{GATE}:\s*(\S+)", cfg, re.M)
    assert m, f"{GATE} is not declared in default.config.yml"
    assert m.group(1) == "false", "deletion defaults on; it must be deliberate"
    assert not re.search(r"^prune_disabled_overrides:", cfg, re.M), (
        "the retired name is declared again — two flags for one decision")


def _daemon_plan():
    spec = importlib.util.spec_from_file_location("prune_guard", FILTER)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["prune_guard"] = mod
    spec.loader.exec_module(mod)
    return mod.nos_host_daemon_plan


def test_host_daemon_bootout_is_not_gated():
    """install_backrest: false only skipped the role. The leftover LaunchAgent
    kept answering. Same split as docker stop: bootout is reversible and
    ungated; only plist deletion waits for uninstall_disabled_services."""
    boot = [t for t in _tasks() if "bootout" in [str(a) for a in _argv(t)]]
    assert boot, (
        "nothing runs `launchctl bootout` for a host daemon that is off. "
        "install_*: false only skips the role, so a leftover LaunchAgent "
        "keeps answering — the backrest case")
    when = str(boot[0].get("when", ""))
    assert GATE not in when, (
        f"the host-daemon bootout is gated on {GATE}. Stopping is reversible; "
        f"putting it behind the deletion flag leaves the declaration unenforced")
    text = TASK.read_text(encoding="utf-8")
    assert "anatomy-graph.json" in text and "nos_host_daemon_plan" in text, (
        "the bootout loop is not enumerated from the anatomy graph")
    assert BACKREST not in text, (
        "a launchd label is hard-coded in prune-disabled.yml — that is a hand "
        "list. Enumerate daemon nodes from state/anatomy-graph.json")


def test_host_daemon_plist_deletion_stays_gated():
    plist = [t for t in _tasks()
             if (t.get("ansible.builtin.file") or {}).get("state") == "absent"
             and "LaunchAgents" in str((t.get("ansible.builtin.file") or {}).get("path", ""))]
    assert plist, "no plist removal for a disabled host daemon"
    for t in plist:
        assert GATE in str(t.get("when", "")), (
            f"plist deletion is not gated on {GATE}: {t.get('name')!r}")


def test_host_daemon_plan_is_the_graph_not_a_hand_list():
    graph = json.loads(GRAPH.read_text(encoding="utf-8"))
    plan = _daemon_plan()(graph)
    labels = {r["label"] for r in plan}
    assert BACKREST in labels, "the measured victim is missing from the plan"
    assert all(r["install_flag"].startswith("install_") for r in plan)
    graph_labels = {
        nid.split(":", 1)[1]
        for nid, n in graph["nodes"].items()
        if n.get("kind") == "daemon"
    }
    assert labels <= graph_labels, "plan invented a daemon the graph does not carry"
    dropped = dict(graph["nodes"])
    dropped.pop(f"daemon:{BACKREST}", None)
    assert BACKREST not in {r["label"] for r in _daemon_plan()({"nodes": dropped})}, (
        "removing the node from the graph still stops it — that is a hand list")
