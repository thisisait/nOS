"""Gate: a host daemon is stopped only for a disablement authored on disk.

Review 2026-10-04 #7: `-e install_backrest=false` booted the LaunchAgent out and
deleted its plist BEFORE the authored-on-disk refusal; `-e install_dnsmasq=false`
booted dnsmasq out and left /etc/resolver/<tld> at a dead 127.0.0.1:53, so every
tenant hostname stopped resolving. Order is parsed; the plans render through real Ansible.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import nos_identity as ni  # noqa: E402
PRUNE = yaml.safe_load((REPO / "tasks/stacks/prune-disabled.yml").read_text())
MAIN = [t for p in yaml.safe_load((REPO / "main.yml").read_text()) for t in (p.get("tasks") or [])]
ON_DISK = "[Stacks] Read the install flags as the ON-DISK config layers declare them"
needs_ansible = pytest.mark.skipif(not shutil.which("ansible-playbook"), reason="renders through real Ansible")


def _idx(pred) -> list[int]:
    return [i for i, t in enumerate(PRUNE) if pred(t)]


def test_no_daemon_is_touched_before_the_refusal():
    refuse = _idx(lambda t: "unauthored_destructive" in str(t.get("when")) and "ansible.builtin.fail" in t)
    touch = _idx(lambda t: "bootout" in str(t.get("ansible.builtin.command"))
                 or "LaunchAgents" in str((t.get("ansible.builtin.file") or {}).get("path")))
    assert refuse and touch, (refuse, touch)
    assert max(refuse) < min(touch), "a daemon is booted out / its plist removed before the run can be refused"
    core = next(i for i, t in enumerate(MAIN) if t.get("import_tasks") == "tasks/stacks/core-up.yml")
    system = next(i for i, t in enumerate(MAIN) if "nos_host_daemon_plan('system')" in str(t))
    assert core < system, "the root-daemon retire runs before the stack layer read the on-disk flags"


def _play(tmp: Path, tasks: list, config: str | None, extra: list[str]) -> dict:
    (tmp / "state").mkdir(exist_ok=True)
    shutil.copy(REPO / "state/anatomy-graph.json", tmp / "state/anatomy-graph.json")
    (tmp / ni.default_layers()[-1].name).write_text("install_backrest: true\ninstall_dnsmasq: true\n")
    if config is not None:
        (tmp / "config.yml").write_text(config)
    elif (tmp / "config.yml").exists():
        (tmp / "config.yml").unlink()
    out = tmp / "out.json"
    play = [{"hosts": "localhost", "gather_facts": False, "connection": "local",
             "vars": {"ansible_os_family": "Darwin", "ansible_facts": {"user_uid": 501}},
             "tasks": tasks + [{"ansible.builtin.copy": {"content": "{{ _out | to_json }}", "dest": str(out)}}]}]
    (tmp / "play.yml").write_text(yaml.safe_dump(play))
    env = {**os.environ, "ANSIBLE_FILTER_PLUGINS": str(REPO / "filter_plugins")}
    r = subprocess.run(["ansible-playbook", "-i", "localhost,", str(tmp / "play.yml"), *extra],
                       capture_output=True, text=True, cwd=tmp, env=env)
    assert r.returncode == 0, r.stdout[-1200:]
    return json.loads(out.read_text())


def _gui_stop(tmp: Path, config: str | None, extra: list[str]) -> list[str]:
    on_disk = next(t for t in PRUNE if t.get("name") == ON_DISK)
    reset = next(t for t in PRUNE if (t.get("ansible.builtin.set_fact") or {}).get("_host_daemon_stop") == [])
    acc = next(t for t in PRUNE if "_host_daemon_stop +" in str(t.get("ansible.builtin.set_fact")))
    fix = {"ansible.builtin.set_fact": {"_host_daemons": [{"label": "x.backrest", "install_flag": "install_backrest"}]}}
    out = {"ansible.builtin.set_fact": {"_out": "{{ _host_daemon_stop | map(attribute='label') | list }}"}}
    return _play(tmp, [on_disk, fix, reset, acc, out], config, extra)


@needs_ansible
def test_a_runtime_only_disablement_stops_no_gui_daemon(tmp_path):
    assert _gui_stop(tmp_path, None, ["-e", "install_backrest=false"]) == [], "a one-off -e stops a daemon"
    assert _gui_stop(tmp_path, "install_backrest: false\n", []) == ["x.backrest"], "positive control: authored off"
    assert _gui_stop(tmp_path, "install_backrest: false\n", ["-e", "install_backrest=true"]) == [], "-e on is stopped"


def _system(tmp: Path, config: str | None, extra: list[str]) -> list[str]:
    """main.yml's root-daemon task with its module swapped for a debug of the same args."""
    on_disk = next(t for t in PRUNE if t.get("name") == ON_DISK)
    task = dict(next(t for t in MAIN if "nos_host_daemon_plan('system')" in str(t)))
    mod = next(k for k in task if k.startswith("ansible.builtin.") and k != "ansible.builtin.debug")
    task["ansible.builtin.debug"] = {"msg": task.pop(mod)}
    for k in ("become", "changed_when", "failed_when", "tags"):
        task.pop(k, None)
    task["register"] = "_r"
    out = {"ansible.builtin.set_fact": {"_out": "{{ _r.results | rejectattr('skipped', 'defined') | map(attribute='msg') | list }}"}}
    return _play(tmp, [on_disk, task, out], config, extra)


@needs_ansible
def test_dnsmasq_off_is_authored_and_takes_its_resolvers_along(tmp_path):
    assert _system(tmp_path, None, ["-e", "install_dnsmasq=false"]) == [], "a one-off -e boots dnsmasq out"
    ran = _system(tmp_path, "install_dnsmasq: false\n", [])
    assert len(ran) == 1 and "bootout" in str(ran[0]), f"positive control: authored off retires nothing: {ran}"
    script = ran[0] if isinstance(ran[0], str) else ""
    assert "/etc/resolver" in script, "dnsmasq is booted out while /etc/resolver still points at it"
    # Run the rendered script against a sandbox: launchctl stubbed, /etc/resolver relocated.
    res, bin_ = tmp_path / "resolver", tmp_path / "bin"
    res.mkdir(), bin_.mkdir()
    (bin_ / "launchctl").write_text("#!/bin/sh\nexit 3\n")
    (bin_ / "launchctl").chmod(0o755)
    (res / "dev.local").write_text("# Generated by Ansible - *.dev.local -> dnsmasq\nnameserver 127.0.0.1\n")
    (res / "corp.example").write_text("nameserver 10.0.0.1\n")
    r = subprocess.run(["/bin/sh", "-c", script.replace("/etc/resolver", str(res))],
                       capture_output=True, text=True, env={**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}"})
    assert r.returncode == 0, r.stderr
    assert sorted(p.name for p in res.iterdir()) == ["corp.example"], "the wrong resolver files went"
