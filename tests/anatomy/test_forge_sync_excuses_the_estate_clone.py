"""The estate's own clone holds no trunk, so forge-sync excuses its seat.

2026-10-24: since the estate converges from ~/.nos/estate (branch `estate`,
moved only by `nos update`), every loop:repo-check run there reported
"local: no local branch 'dev'" and forge-sync rc 2 — a holder that was never
one. Its seat is excused like a forge declared off; a dev tree still reads its
local branch.
"""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _sync():
    spec = importlib.util.spec_from_file_location("_forge_sync_estate", REPO / "tools" / "forge-sync.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Driver:
    @staticmethod
    def _yaml_lookup(*_a, **_k):
        return "false"  # both forges declared off: only local and github are read


def _clone(tmp: Path, branch: str) -> Path:
    def git(*a, cwd):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=cwd, check=True, capture_output=True)
    origin, clone = tmp / "origin", tmp / "clone"
    origin.mkdir()
    git("init", "-q", "-b", "dev", cwd=origin)
    git("commit", "-q", "--allow-empty", "-m", "A", cwd=origin)
    git("clone", "-q", str(origin), str(clone), cwd=tmp)
    git("checkout", "-q", "-B", branch, "origin/dev", cwd=clone)
    if branch != "dev":
        git("branch", "-q", "-D", "dev", cwd=clone)
    return clone


def test_the_estate_clone_seat_is_excused(tmp_path):
    sync = _sync()
    sync.REPO = _clone(tmp_path, "estate")
    tips = sync.read_tips(_Driver, "dev")
    assert tips["local"].get("declared_off") and not tips["local"]["error"], tips["local"]
    assert tips["github"]["sha"], tips["github"]


def test_a_dev_tree_still_reads_its_local_branch(tmp_path):
    sync = _sync()
    sync.REPO = _clone(tmp_path, "dev")
    tips = sync.read_tips(_Driver, "dev")
    assert tips["local"]["sha"] and not tips["local"].get("declared_off"), tips["local"]
