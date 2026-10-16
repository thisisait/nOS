"""Gate: without copy #1 its agent and backup.sh are removed, and the reader says so.

2026-10-16, a core client host (no RustFS, install_backup off): an agent from an
earlier fuller install likely still ran an old ~/.nos/backup.sh against a RustFS
that is gone, and red-status read its stale backup-status.json as the truth.
Ruling: the role removes the agent + script when backup_copy1_enabled is off,
the removal ladder knows both, red-status says "copy #1 not installed".

absent.yml is EXECUTED by a scratch play (HOME = tmp_path, nos_service_manager
= none so no launchctl/systemctl is ever called); the rest is read from the
playbook's own YAML.
"""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import nos_identity as ni  # noqa: E402

LABEL = "eu.thisisait.nos.backup.rustfs"
EXPORTER = "eu.thisisait.nos.backup.exporter"


def _main_tasks():
    out = []

    def walk(node):
        if isinstance(node, list):
            for n in node:
                walk(n)
        elif isinstance(node, dict):
            for key in ("ansible.builtin.import_role", "ansible.builtin.include_role"):
                if isinstance(node.get(key), dict) and node[key].get("name") == "pazny.backup":
                    out.append(node)
            for v in node.values():
                if isinstance(v, (list, dict)):
                    walk(v)
    walk(yaml.safe_load((REPO / "main.yml").read_text(encoding="utf-8")))
    return out


def test_main_runs_the_role_or_its_absent_tasks_on_the_one_derivation():
    sites = _main_tasks()
    whens = [str(s.get("when")) for s in sites]
    assert any("backup_copy1_enabled" in w and "not" not in w for w in whens), whens
    absent = [s for s in sites if (s.get("ansible.builtin.include_role") or {}).get("tasks_from") == "absent"]
    assert absent, "no include of pazny.backup tasks_from: absent in main.yml"
    inc = absent[0]
    assert "not" in str(inc.get("when")) and "backup_copy1_enabled" in str(inc.get("when"))
    assert inc["ansible.builtin.include_role"].get("apply", {}).get("tags") and inc.get("tags"), (
        "include_role needs both apply.tags and tags or --tags never reaches it")


def test_absent_removes_the_agent_and_the_script(tmp_path):
    home = tmp_path
    files = [home / f"Library/LaunchAgents/{LABEL}.plist", home / f"Library/LaunchAgents/{EXPORTER}.plist",
             home / ".nos/backup.sh", home / ".nos/backup-verify.sh", home / ".nos/backup_status_exporter.py"]
    for f in files:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("stale")
    play = [{"hosts": "localhost", "connection": "local", "gather_facts": True,
             "gather_subset": ["!all", "min"],
             "vars": {"nos_service_manager": "none", "node_exporter_textfile_dir": str(home / "prom"),
                      "ansible_python_interpreter": sys.executable},
             "tasks": [{"ansible.builtin.include_role": {"name": "pazny.backup", "tasks_from": "absent"}}]}]
    (tmp_path / "play.yml").write_text(yaml.safe_dump(play))
    (tmp_path / "ansible.cfg").write_text("[defaults]\n")
    env = {**os.environ, "HOME": str(home), "ANSIBLE_CONFIG": str(tmp_path / "ansible.cfg"),
           "ANSIBLE_ROLES_PATH": str(REPO / "roles"), "ANSIBLE_LOCALHOST_WARNING": "false",
           "ANSIBLE_INVENTORY_UNPARSED_WARNING": "false"}
    run = subprocess.run([sys.executable, "-m", "ansible.cli.playbook", "-i", "localhost,",
                          str(tmp_path / "play.yml")], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert run.returncode == 0, run.stdout[-3000:] + run.stderr[-1500:]
    left = [str(f) for f in files if f.exists()]
    assert not left, f"copy #1 left behind: {left}"


def test_the_removal_ladder_knows_them():
    blank = (REPO / "tasks/blank-reset.yml").read_text(encoding="utf-8")
    assert f"{LABEL}.plist" in blank and f"{EXPORTER}.plist" in blank
    rs = (REPO / "tasks/removal-set.yml").read_text(encoding="utf-8")
    assert "bone_state_dir | default(ansible_facts['env']['HOME'] + '/.nos')" in rs, (
        "~/.nos (backup.sh, backup-verify.sh) left the source-level removal set")


def _red():
    spec = importlib.util.spec_from_file_location("red_status", REPO / "tools/red-status.py")
    red = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(red)
    return red


def test_the_reader_says_copy1_is_not_installed_and_ignores_its_stale_status(tmp_path, monkeypatch):
    red = _red()
    flags = ni.install_flags(ni.profile_layers(REPO / "profiles/core.yml"))
    stale = tmp_path / "backup-status.json"
    stale.write_text(json.dumps({"sources": [{"name": "postgres", "success": False, "timestamp": 1}]}))
    direct = tmp_path / "backup-restic-status.json"
    direct.write_text(json.dumps({"sources": [
        {"name": "postgres", "success": True, "off": False, "timestamp": 2},
        {"name": "dir-tenants", "success": False, "off": False, "timestamp": 2}]}))
    monkeypatch.setattr(red, "BACKUP_STATUS", stale)
    monkeypatch.setattr(red, "BACKUP_RESTIC_STATUS", direct)
    monkeypatch.setattr(red, "_install_flags", lambda: flags)
    bk = red.backups()
    assert bk["copy1"] is False
    assert bk["failed"] == ["dir-tenants"], "the stale copy-#1 file was read, or the direct one was not"
    assert any("copy #1 not installed" in h for h in red.hold_lines({"backups": bk}))
