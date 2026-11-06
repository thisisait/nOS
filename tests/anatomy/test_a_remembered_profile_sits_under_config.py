"""A host's profile is remembered in config.yml and loads UNDER it.

11-01 on the Linux mini: `-e @profiles/core.yml` is extra-vars, so it silently beat config.yml's
install_kiwix: true; and a plain `nos` without the -e forgot the profile and converged the defaults.
Ruling 11-06: config.yml names it (`nos_profile: core`). This runs main.yml's own config/profile
tasks in a throwaway play and reads the resolved values.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]


def _tasks():
    play = yaml.safe_load((REPO / "main.yml").read_text(encoding="utf-8"))[0]
    pre = play["pre_tasks"]
    i = next(n for n, t in enumerate(pre) if t.get("name") == "Include playbook configuration overrides.")
    return [t for t in pre[i:i + 6] if t.get("name") == "Include playbook configuration overrides."
            or str(t.get("name", "")).startswith("[Profile]")]


def _resolve(tmp: Path, config: dict) -> dict:
    (tmp / "profiles").mkdir()
    (tmp / "profiles" / "p.yml").write_text("install_x: false\ninstall_y: true\n")
    (tmp / "config.yml").write_text(yaml.safe_dump(config))
    play = [{"hosts": "localhost", "connection": "local", "gather_facts": False,
             "vars": {"nos_profile": "", "install_x": "default", "install_y": "default"},
             "tasks": _tasks() + [{"copy": {"dest": str(tmp / "out.json"),
                                            "content": "{{ {'x': install_x, 'y': install_y} | to_json }}"}}]}]
    (tmp / "play.yml").write_text(yaml.safe_dump(play, sort_keys=False))
    p = subprocess.run(["ansible-playbook", "-i", "localhost,", str(tmp / "play.yml")],
                       cwd=tmp, capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stdout[-1500:]
    return json.loads((tmp / "out.json").read_text())


@pytest.mark.skipif(not shutil.which("ansible-playbook"), reason="no ansible-playbook: UNKNOWN, not green")
def test_config_beats_the_profile_and_the_profile_beats_defaults(tmp_path):
    got = _resolve(tmp_path, {"nos_profile": "p", "install_x": True})
    assert got == {"x": True, "y": True}, got


@pytest.mark.skipif(not shutil.which("ansible-playbook"), reason="no ansible-playbook: UNKNOWN, not green")
def test_no_profile_named_loads_none(tmp_path):
    assert _resolve(tmp_path, {"install_x": True}) == {"x": True, "y": "default"}
