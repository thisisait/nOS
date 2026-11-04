"""A Paperclip agent never commits inside a host-mounted repo (operator ruling B3, 2026-11-03).

A host workspace mounts read-only unless declared rw, and its .git is overlaid read-only
either way, so even an rw workspace cannot plant a hook or rewrite git config the operator
then runs on the host. The overlay is emitted only where the role's stat found a .git (dir,
or file = linked worktree): a bind mount creates a missing source, so an unconditional
overlay planted an empty .git in every non-repo workspace. A .git dir or bare repo is refused.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import jinja2
import pytest
import yaml

from test_paperclip_agents_have_a_workspace import HOME, TASKS, _svc


def _stat(name, exists):
    return {"results": [{"item": {"name": name}, "stat": {"exists": exists}}]}


@pytest.mark.parametrize("mode", [None, "rw", "ro"])
def test_a_host_workspace_git_is_overlaid_read_only(mode):
    w = {"name": "hnedweb", "path": f"{HOME}/projects/hnedweb"}
    if mode:
        w["mode"] = mode
    vols = _svc(paperclip_host_workspaces=[w], _paperclip_ws_git=_stat("hnedweb", True))["volumes"]
    assert f"{HOME}/projects/hnedweb:/workspaces/hnedweb:{mode or 'ro'}" in vols, vols
    assert f"{HOME}/projects/hnedweb/.git:/workspaces/hnedweb/.git:ro" in vols, vols


def test_a_workspace_without_git_gets_no_overlay():
    w = {"name": "notes", "path": f"{HOME}/projects/notes", "mode": "rw"}
    vols = _svc(paperclip_host_workspaces=[w], _paperclip_ws_git=_stat("notes", False))["volumes"]
    assert f"{HOME}/projects/notes:/workspaces/notes:rw" in vols, vols
    assert not [v for v in vols if "/.git:" in v], vols


def _accepted(path):
    tasks = yaml.safe_load(TASKS.read_text())
    guard = [t for t in tasks if "ansible.builtin.assert" in t and "paperclip_host_workspaces" in str(t)]
    that = [c for t in guard for c in t["ansible.builtin.assert"]["that"]]
    env = jinja2.Environment()
    env.filters["realpath"] = lambda v: str(Path(v)).rstrip("/") or "/"
    env.tests["match"] = lambda v, pat: re.match(pat, str(v)) is not None
    item = {"name": "w", "path": path}
    # The role's stat tasks, answered by the real filesystem, as Ansible registers them.
    stats = {}
    for t in tasks:
        if "ansible.builtin.stat" in t and "register" in t:
            p = env.from_string(t["ansible.builtin.stat"]["path"]).render(item=item)
            stats[t["register"]] = {"results": [{"item": item, "stat": {
                "exists": os.path.lexists(p), "isreg": os.path.isfile(p), "isdir": os.path.isdir(p)}}]}
    return all(env.from_string("{{ (" + c + ") | string }}").render(
        item=item, _i=0, nos_data_root="/data", ansible_facts={"env": {"HOME": HOME}}, **stats) == "True"
        for c in that)


@pytest.mark.parametrize("path", [f"{HOME}/projects/hnedweb/.git", f"{HOME}/projects/hnedweb/.git/hooks"])
def test_a_git_dir_is_never_a_workspace(path):
    assert not _accepted(path), f"{path} must be refused as a workspace"


def test_a_bare_repo_is_never_a_workspace_but_a_clone_is(tmp_path):
    bare, clone = tmp_path / "site.git", tmp_path / "site"
    (bare / "objects").mkdir(parents=True)
    (bare / "HEAD").write_text("ref: refs/heads/main\n")
    (clone / ".git" / "objects").mkdir(parents=True)
    assert not _accepted(str(bare)), f"{bare} (bare repo) must be refused as a workspace"
    assert _accepted(str(clone)), f"{clone} (a clone's work tree) must be accepted"
