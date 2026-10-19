"""The `unix` realm never takes over a login nOS did not create.

On a shared host (DGX Spark) a roster name can match a real person's existing
login. pazny.linux.users would then give it the tier group, chown its home
0700, set its password and — for a switched-off synthetic — lock it. The role
must REFUSE such a login unless config.yml lists it in linux_users_adopted;
a login nOS made carries linux_users_marker in its GECOS and passes.

End to end: the role's own guard tasks run under ansible-playbook against a
host whose passwd already holds the name.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
ROLE = REPO / "roles" / "pazny.linux.users"


def _run(tmp_path, gecos, adopted):
    tasks = yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())
    users = next(i for i, t in enumerate(tasks) if "ansible.builtin.user" in t)
    # Every task between the roster fact and the login task, minus the host's own
    # passwd read (the fake passwd below stands in for it).
    guard = [t for t in tasks[:users]
             if not any(k in t for k in ("ansible.builtin.getent", "ansible.builtin.group"))
             and "_unix_people" not in (t.get("ansible.builtin.set_fact") or {})]
    defaults = yaml.safe_load((ROLE / "defaults" / "main.yml").read_text())
    passwd = {"alice": ["x", "1000", "1000", gecos, "/home/alice", "/bin/bash"]}
    play = [{
        "hosts": "localhost", "gather_facts": False, "connection": "local",
        "vars": {**defaults, "linux_users_adopted": adopted,
                 "_unix_people": [{"name": "alice", "tier": 3, "password": "pw", "active": True}]},
        "tasks": [{"ansible.builtin.set_fact": {"ansible_facts": {"getent_passwd": passwd}}}] + guard,
    }]
    pb = tmp_path / "p.yml"
    pb.write_text(yaml.safe_dump(play))
    env = {**os.environ, "ANSIBLE_STDOUT_CALLBACK": "json", "ANSIBLE_NOCOLOR": "1"}
    r = subprocess.run(["ansible-playbook", "-i", "localhost,", str(pb)],
                       capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL)
    return r.returncode, r.stdout + r.stderr


@pytest.mark.skipif(not shutil.which("ansible-playbook"), reason="ansible-playbook not on PATH")
def test_a_foreign_login_is_refused(tmp_path):
    rc, out = _run(tmp_path, "Alice Real,,,", [])
    assert rc != 0, f"a pre-existing login nOS did not create was taken over:\n{out[-2000:]}"
    assert "linux_users_adopted" in out, "the refusal must say how to hand the login over"


@pytest.mark.skipif(not shutil.which("ansible-playbook"), reason="ansible-playbook not on PATH")
def test_an_own_or_adopted_login_passes(tmp_path):
    marker = yaml.safe_load((ROLE / "defaults" / "main.yml").read_text())["linux_users_marker"]
    rc, out = _run(tmp_path, marker, [])
    assert rc == 0, f"a login nOS created was refused:\n{out[-2000:]}"
    rc, out = _run(tmp_path, "Alice Real,,,", ["alice"])
    assert rc == 0, f"a login the operator adopted was refused:\n{out[-2000:]}"


def test_a_created_login_carries_the_marker():
    tasks = yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())
    user = next(t["ansible.builtin.user"] for t in tasks if "ansible.builtin.user" in t)
    assert "linux_users_marker" in user.get("comment", ""), "an unmarked login reads as foreign next run"
    assert json.dumps(yaml.safe_load((ROLE / "defaults" / "main.yml").read_text())["linux_users_adopted"]) == "[]"
