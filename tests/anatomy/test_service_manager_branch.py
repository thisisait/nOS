"""Anatomy CI gate — host-daemon service-manager branching (Linux port).

The anatomy host daemons run via launchd on macOS and systemd --user on Linux
(2026-05-25 port). This gate pins the branch so a future edit can't silently
revert a daemon to launchd-only (which would break a Linux blank) or drop the
Darwin gate on the mac-coupled agents:

  1. Each PORTED daemon (bone/pulse/wing) gates its launchd plist render on
     `nos_service_manager` AND includes pazny.linux.systemd_user::ensure_unit.
  2. The mac-coupled agents (openclaw/hermes) are Darwin-gated in main.yml.
  3. The reusable systemd_user abstraction (ensure_unit + service/timer
     templates) exists.
"""

from __future__ import annotations

import pathlib

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
PORTED_DAEMONS = ["bone", "pulse", "wing"]
DARWIN_GATED_AGENTS = ["pazny.openclaw", "pazny.hermes"]


def _tasks(role: str) -> list:
    return yaml.safe_load((REPO / "roles" / f"pazny.{role}" / "tasks" / "main.yml").read_text())


def _as_list(v):
    return v if isinstance(v, list) else [v]


@pytest.mark.parametrize("role", PORTED_DAEMONS)
def test_plist_render_is_service_manager_gated(role):
    tasks = _tasks(role)
    plist = [t for t in tasks
             if isinstance(t, dict)
             and isinstance(t.get("ansible.builtin.template"), dict)
             and str(t["ansible.builtin.template"].get("src", "")).endswith(".plist.j2")]
    assert plist, f"{role}: no launchd plist-render task found"
    for t in plist:
        whens = " ".join(str(w) for w in _as_list(t.get("when", [])))
        assert "nos_service_manager" in whens, \
            f"{role}: plist render not gated on nos_service_manager (when={t.get('when')!r})"


@pytest.mark.parametrize("role", PORTED_DAEMONS)
def test_has_systemd_user_branch(role):
    tasks = _tasks(role)
    inc = [t for t in tasks
           if isinstance(t, dict)
           and isinstance(t.get("ansible.builtin.include_role"), dict)
           and t["ansible.builtin.include_role"].get("name") == "pazny.linux.systemd_user"]
    assert inc, f"{role}: no pazny.linux.systemd_user include (Linux branch missing)"
    for t in inc:
        whens = " ".join(str(w) for w in _as_list(t.get("when", [])))
        assert "systemd-user" in whens, \
            f"{role}: systemd_user include not gated on systemd-user (when={t.get('when')!r})"


def _walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


@pytest.mark.parametrize("agent", DARWIN_GATED_AGENTS)
def test_mac_coupled_agents_darwin_gated(agent):
    play = yaml.safe_load((REPO / "main.yml").read_text())
    hits = [n for n in _walk(play)
            if isinstance(n.get("ansible.builtin.import_role"), dict)
            and n["ansible.builtin.import_role"].get("name") == agent]
    assert hits, f"{agent}: import_role not found in main.yml"
    for n in hits:
        whens = " ".join(str(w) for w in _as_list(n.get("when", [])))
        assert "Darwin" in whens, \
            f"{agent}: import not Darwin-gated (when={n.get('when')!r})"


def test_systemd_user_abstraction_present():
    base = REPO / "roles" / "pazny.linux.systemd_user"
    assert (base / "tasks" / "ensure_unit.yml").is_file()
    assert (base / "templates" / "service.j2").is_file()
    assert (base / "templates" / "timer.j2").is_file()
