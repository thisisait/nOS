"""A Paperclip agent never commits inside a host-mounted repo (operator ruling B3, 2026-11-03).

A host workspace mounts read-only unless declared rw, and its .git is overlaid read-only
either way, so even an rw workspace cannot plant a hook or rewrite git config the operator
then runs on the host. A workspace that is itself a .git dir is refused by the role.
"""
from __future__ import annotations

import re
from pathlib import Path

import jinja2
import pytest
import yaml

from test_paperclip_agents_have_a_workspace import HOME, TASKS, _svc


@pytest.mark.parametrize("mode", [None, "rw", "ro"])
def test_a_host_workspace_git_is_overlaid_read_only(mode):
    w = {"name": "hnedweb", "path": f"{HOME}/projects/hnedweb"}
    if mode:
        w["mode"] = mode
    vols = _svc(paperclip_host_workspaces=[w])["volumes"]
    assert f"{HOME}/projects/hnedweb:/workspaces/hnedweb:{mode or 'ro'}" in vols, vols
    assert f"{HOME}/projects/hnedweb/.git:/workspaces/hnedweb/.git:ro" in vols, vols


@pytest.mark.parametrize("path", [f"{HOME}/projects/hnedweb/.git", f"{HOME}/projects/hnedweb/.git/hooks"])
def test_a_git_dir_is_never_a_workspace(path):
    guard = [t for t in yaml.safe_load(TASKS.read_text()) if "ansible.builtin.assert" in t
             and "paperclip_host_workspaces" in str(t)]
    that = guard[0]["ansible.builtin.assert"]["that"]
    env = jinja2.Environment()
    env.filters["realpath"] = lambda v: str(Path(v)).rstrip("/") or "/"
    env.tests["match"] = lambda v, pat: re.match(pat, str(v)) is not None
    ok = all(env.from_string("{{ (" + c + ") | string }}").render(
        item={"name": "w", "path": path}, nos_data_root="/data",
        ansible_facts={"env": {"HOME": HOME}}) == "True" for c in that)
    assert not ok, f"{path} must be refused as a workspace"
