"""Kiwix restarts when its library changes, however the ZIMs arrived.

THE SYMPTOM (2026-11-01, the Linux mini). 335 ZIMs restored by rsync into the data
dir; `nos --tags kiwix` went green and Kiwix kept serving 1 book: the restart fired
only for a ZIM the role downloaded itself, and kiwix-serve reads /data/*.zim once.

THE CHECK. Runs roles/pazny.kiwix/tasks/library.yml in a throwaway play (docker_bin
is `true`, so the handler restarts nothing): a new library is a change, the same
library is not, one more ZIM is. CEILING: the restart's effect is the live catalog.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROLE = Path(__file__).resolve().parents[2] / "roles" / "pazny.kiwix"
PLAY = """- hosts: localhost
  connection: local
  gather_facts: false
  vars: {{docker_bin: "true", kiwix_data_dir: "{data}"}}
  tasks:
    - ansible.builtin.include_tasks: {tasks}
  handlers:
    - ansible.builtin.import_tasks: {handlers}
"""


def _converge(tmp: Path, data: Path) -> str:
    play = tmp / "play.yml"
    play.write_text(PLAY.format(data=data, tasks=ROLE / "tasks/library.yml", handlers=ROLE / "handlers/main.yml"))
    out = subprocess.run(["ansible-playbook", str(play)], capture_output=True, text=True, timeout=120,
                         env={**os.environ, "ANSIBLE_CONFIG": str(tmp / "none.cfg"), "ANSIBLE_LOCALHOST_WARNING": "False"},
                         cwd=tmp)
    assert out.returncode == 0, out.stdout[-1500:] + out.stderr[-800:]
    return out.stdout


def test_a_library_change_restarts_kiwix(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "alpinelinux.zim").write_bytes(b"x" * 10)
    assert "RUNNING HANDLER" in _converge(tmp_path, data), "a first library must restart Kiwix once"
    assert "RUNNING HANDLER" not in _converge(tmp_path, data), "the same library must not restart Kiwix"
    (data / "wikipedia.zim").write_bytes(b"y" * 20)
    assert "RUNNING HANDLER" in _converge(tmp_path, data), "a ZIM that arrived by rsync must restart Kiwix"
