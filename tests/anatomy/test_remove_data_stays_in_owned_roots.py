"""remove=data refuses a path outside the nOS roots or on a protected path (destructive, ssot/doctrine/gates.md §7).

2026-11-11 review: the owned-roots guard took the whole external SSD as a root, so a *_dir pointed
at the restic repo beside the service dirs (/Volumes/SSD1TB/nos-restic) passed. This runs the real
assert task from tasks/removal-set.yml, not a copy of its logic, on the five shapes that matter.
Row nos-owned-paths-realpath: the check compared strings, so a *_dir that is a symlink inside a root
pointing outside it passed; the planted-symlink case below pins the resolved comparison.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
TASK = "[Removal-set] Every data-level path lies under a root nOS owns"
pytestmark = pytest.mark.skipif(not shutil.which("ansible-playbook"), reason="ansible-playbook runs the assert")

ROOTS = ["/home/op/nos", "/home/op/stacks", "/Volumes/SSD1TB"]


def _run(tmp_path: Path, dirs: list[str], roots: list[str] = ROOTS) -> int:
    task = next(t for t in yaml.safe_load((REPO / "tasks/removal-set.yml").read_text()) if t.get("name") == TASK)
    play = [{"hosts": "localhost", "gather_facts": False, "connection": "local",
             "vars": {"_removal_roots": roots, "_blank_dirs": dirs, "restic_repo": "",
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


def test_a_symlink_out_of_a_root_is_refused(tmp_path):
    """A *_dir lexically under a root whose symlink leads outside it is refused; a real dir passes."""
    root, outside = tmp_path / "root", tmp_path / "outside"
    (root / "real").mkdir(parents=True)
    (outside / "sub").mkdir(parents=True)
    (root / "link").symlink_to(outside)
    assert _run(tmp_path, [str(root / "real"), str(root / "gone")], [str(root)]) == 0
    assert _run(tmp_path, [str(root / "link")], [str(root)]) != 0, "symlink out of the root passed"
    assert _run(tmp_path, [str(root / "link" / "sub")], [str(root)]) != 0, "path through the symlink passed"


def test_the_default_layers_remove_only_inside_the_roots():
    """Every rendered default-layer _blank_dirs entry (all install_* on) lies under a declared root."""
    sys.path.insert(0, str(REPO / "tools"))
    import importlib.util
    spec = importlib.util.spec_from_file_location("managed_status", REPO / "tools/managed-status.py")
    ms = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ms)
    env = ms.jinja()
    ctx = ms.config_ctx(env)
    data, _all, _keep = ms.removal_levels(env, ctx)
    homes = yaml.safe_load(env.from_string((REPO / "state/genome/owned-paths.yml").read_text()).render(ctx))["homes"]
    roots = {ctx["nos_data_root"], ctx["stacks_dir"]} | {h["path"] for h in homes if h["kind"] in ("data", "other-tool")}
    roots = {r.rstrip("/") for r in roots}
    stray = sorted(d for d in data if not ms.covered(d, roots))
    assert not stray, f"remove=data would delete paths outside every nOS root: {stray}"
