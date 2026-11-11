"""remove=data refuses a path outside the nOS roots or on a protected path (destructive, gates.md §7).

2026-11-11 review: the owned-roots guard took the whole external SSD as a root, so a *_dir pointed
at the restic repo beside the service dirs (/Volumes/SSD1TB/nos-restic) passed. This runs the real
assert task from tasks/removal-set.yml, not a copy of its logic, on the five shapes that matter.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
TASK = "[Removal-set] Every data-level path lies under a root nOS owns"
pytestmark = pytest.mark.skipif(not shutil.which("ansible-playbook"), reason="ansible-playbook runs the assert")

ROOTS = ["/home/op/nos", "/home/op/stacks", "/Volumes/SSD1TB"]


def _run(tmp_path: Path, dirs: list[str]) -> int:
    task = next(t for t in yaml.safe_load((REPO / "tasks/removal-set.yml").read_text()) if t.get("name") == TASK)
    play = [{"hosts": "localhost", "gather_facts": False, "connection": "local",
             "vars": {"_removal_roots": ROOTS, "_blank_dirs": dirs, "restic_repo": "",
                      "configure_external_storage": True, "external_storage_root": "/Volumes/SSD1TB",
                      "ansible_facts": {"env": {"HOME": "/home/op"}}},
             "tasks": [task]}]
    pb = tmp_path / "pb.yml"
    pb.write_text(yaml.safe_dump(play, sort_keys=False))
    r = subprocess.run(["ansible-playbook", "-i", "localhost,", str(pb)], cwd=tmp_path,
                       capture_output=True, text=True, timeout=120)
    return r.returncode


@pytest.mark.parametrize("dirs,ok", [
    (["/home/op/nos/platform/services/dolibarr", "/Volumes/SSD1TB/calibre"], True),
    (["/home/op/Documents"], False),
    (["/Volumes/SSD1TB/nos-restic"], False),
    (["/Volumes/SSD1TB"], False),
    (["/Volumes/SSD1TB/docker/vms"], False),
], ids=["owned", "outside-roots", "restic-repo", "ssd-root-ancestor", "docker-image"])
def test_the_guard_refuses_what_nos_does_not_own(tmp_path, dirs, ok):
    rc = _run(tmp_path, dirs)
    assert (rc == 0) == ok, f"{dirs}: rc={rc}, expected {'pass' if ok else 'refusal'}"
