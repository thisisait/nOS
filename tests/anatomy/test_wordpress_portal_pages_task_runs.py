"""The portal-pages task must reach `wp post create` as ONE command.

Blank 2026-09-29: the task used a folded scalar (`>`), and YAML keeps the
newlines of more-indented lines, so the `if` body became four shell commands
and failed with "wp: command not found" on every first install. This gate
renders the task the way Ansible does (YAML + Jinja), runs it under a stub
`docker` that answers an empty page list, and asserts the create call
arrives whole.
"""
from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import jinja2
import yaml

REPO = Path(__file__).resolve().parents[2]
POST = REPO / "roles/pazny.wordpress/tasks/post.yml"
DEFAULTS = REPO / "roles/pazny.wordpress/defaults/main.yml"


def _task() -> dict:
    tasks = yaml.safe_load(POST.read_text(encoding="utf-8"))
    return next(t for t in tasks if t.get("name", "").endswith("Ensure client portal pages"))


def test_the_create_call_arrives_as_one_command(tmp_path: Path) -> None:
    stub = tmp_path / "docker"
    log = tmp_path / "calls.log"
    stub.write_text(f'#!/bin/sh\necho "$*" >> "{log}"\nexit 0\n')
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)

    env = jinja2.Environment()
    env.filters["quote"] = lambda v: "'" + str(v).replace("'", "'\\''") + "'"
    page = yaml.safe_load(DEFAULTS.read_text(encoding="utf-8"))["wordpress_portal_pages"][0]
    script = env.from_string(_task()["ansible.builtin.shell"]).render(docker_bin=str(stub), item=page)

    run = subprocess.run(["/bin/sh", "-c", script], capture_output=True, text=True,
                         env={**os.environ, "PATH": str(tmp_path)})
    assert run.returncode == 0 and run.stderr == "", run.stderr
    calls = log.read_text().splitlines()
    assert len(calls) == 2, calls
    assert "wp post create" in calls[1] and page["content"] in calls[1], calls[1]
