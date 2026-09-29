"""Paperclip's first admin invite must actually be created on a blank.

`onboard --yes` writes config.json as local_trusted while the container runs
authenticated through the env; the server reads the env, the CLI reads the
file, so `auth bootstrap-ceo` declined ("only required for authenticated
mode", exit 0) and every blank produced an instance nobody could log in to.
The align step runs BEFORE the bootstrap; its node snippet is executed here
against the quickstart file: ALIGNED once, aligned after.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
POST = REPO / "roles/pazny.paperclip/tasks/post.yml"


def _tasks():
    return yaml.safe_load(POST.read_text())


def test_the_align_step_precedes_the_bootstrap():
    names = [t["name"] for t in _tasks()]
    align = names.index("[pazny.paperclip Post] Align config.json with the mode the server runs under")
    onboard = names.index("[pazny.paperclip Post] Initialize Paperclip instance (non-interactive onboard)")
    boot = names.index("[pazny.paperclip Post] Bootstrap CEO admin invite (first-run only)")
    assert onboard < align < boot


def test_the_snippet_aligns_a_quickstart_config_once(tmp_path):
    task = next(t for t in _tasks() if t["name"].endswith("mode the server runs under"))
    js = task["ansible.builtin.shell"].split("node -e '", 1)[1].rsplit("'", 1)[0]
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"server": {"deploymentMode": "local_trusted", "bind": "loopback", "allowedHostnames": ["x"]}}))
    js = js.replace("/paperclip/instances/default/config.json", str(cfg))
    run = lambda: subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout.strip()
    assert run() == "ALIGNED"
    got = json.loads(cfg.read_text())["server"]
    assert got["deploymentMode"] == "authenticated" and got["allowedHostnames"] == ["x"]
    assert run() == "aligned"


def test_the_invite_is_kept_not_only_printed():
    keep = next(t for t in _tasks() if "Keep the CEO invite URL" in t["name"])
    assert keep["no_log"] is True and keep["ansible.builtin.copy"]["mode"] == "0600"
    assert "Invite URL" in keep["ansible.builtin.copy"]["content"]
