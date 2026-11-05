"""An -e @profile silently outranked config.yml: the wrapper printed only the
profile name. It must name each disagreeing toggle, both values and the winner
before ansible-playbook runs (--print-cmd exits before any exec)."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_profile_conflict_with_config_is_named(tmp_path):
    (tmp_path / "profiles").mkdir()
    (tmp_path / "profiles" / "core.yml").write_text(
        (REPO / "profiles" / "core.yml").read_text())
    (tmp_path / "config.yml").write_text(
        "install_kiwix: true   # mine\ninstall_gitlab: false\n")
    env = dict(os.environ, HOME=str(tmp_path / "home"), NOS_SRC=str(tmp_path))
    r = subprocess.run([str(REPO / "tools" / "nos"), "--print-cmd", "-e", "@profiles/core.yml"],
                       env=env, capture_output=True, text=True, timeout=15)
    assert r.returncode == 0, r.stderr
    line = next((l for l in r.stderr.splitlines() if "install_kiwix" in l), "")
    assert "true" in line and "false" in line and "profile wins" in line, r.stderr
    assert "install_gitlab" not in r.stderr  # agreeing keys stay quiet
