"""A renamed skill leaves no dangling link behind; a link nOS did not make stays.

2026-10-06: renaming cortex-query to keap-recall would have left
~/.claude/skills/cortex-query pointing at a deleted library dir on every shelf,
because tasks/skills.yml only ever added links. Runs the real task file through
Ansible in a temp HOME (pattern: test_claude_cli_respects_an_existing_install.py).
"""
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
TASKS = REPO / "tasks/skills.yml"
needs_ansible = pytest.mark.skipif(importlib.util.find_spec("ansible") is None, reason="runs the task through real Ansible")


@needs_ansible
def test_dangling_library_links_are_pruned_and_foreign_links_survive(tmp_path):
    lib = tmp_path / "files/anatomy/skills"
    (lib / "alive").mkdir(parents=True)
    (lib / "alive/SKILL.md").write_text("---\nname: alive\ndescription: x\n---\n# alive\n")
    shelf = tmp_path / "home/.claude/skills"
    shelf.mkdir(parents=True)
    (shelf / "renamed-away").symlink_to(lib / "renamed-away")       # ours, dangling
    (shelf / "foreign-dangling").symlink_to(tmp_path / "elsewhere/x")  # not ours
    (tmp_path / "theirs").mkdir()
    (shelf / "foreign-live").symlink_to(tmp_path / "theirs")          # not ours

    play = [{"hosts": "localhost", "connection": "local", "gather_facts": False,
             "vars": {"ansible_python_interpreter": sys.executable,
                      "nos_skill_consumers": [{"id": "claude", "kind": "main", "dir": str(shelf)},
                                              {"id": "hermes", "kind": "agent",
                                               "dir": str(tmp_path / "home/.hermes/skills")}]},
             "tasks": [{"import_tasks": str(TASKS)}]}]
    (tmp_path / "play.yml").write_text(yaml.safe_dump(play))
    env = {**os.environ, "HOME": str(tmp_path / "home"), "ANSIBLE_LOCAL_TEMP": str(tmp_path / ".ansible")}
    r = subprocess.run([sys.executable, "-m", "ansible.cli.playbook", "-i", "localhost,", str(tmp_path / "play.yml")],
                       capture_output=True, text=True, cwd=tmp_path, env=env, timeout=300)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-1000:]

    assert not (shelf / "renamed-away").is_symlink(), "a link into the library whose skill is gone was left dangling"
    assert (shelf / "foreign-dangling").is_symlink(), "a dangling link nOS did not make was removed"
    assert (shelf / "foreign-live").is_symlink(), "a live link nOS did not make was removed"
    assert (shelf / "alive").resolve() == (lib / "alive").resolve(), "the live skill was not linked"
    assert not (tmp_path / "home/.hermes").exists(), "a shelf was created for an absent harness"
