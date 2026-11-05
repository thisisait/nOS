"""tools/worktree-prune.py lists, and with --confirm removes, only merged clean worktrees.

WHY. 2026-11-02: 65 GB of agent worktrees, the disk at 98 %. A pruner that took
one with uncommitted work, an unlanded branch, or a nested child under the
gitignored .claude/ would lose work nobody can recover. Fixture repo in tmp only.
"""

from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import subprocess
import sys

TOOL = pathlib.Path(__file__).resolve().parents[2] / "tools" / "worktree-prune.py"


def git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
                   cwd=cwd, check=True, capture_output=True, text=True)


def commit(cwd, name):
    (pathlib.Path(cwd) / name).write_text(name)
    git(cwd, "add", name)
    git(cwd, "commit", "-qm", name)


def prune(repo, *args):
    r = subprocess.run([sys.executable, str(TOOL), "--repo", str(repo), "--no-size", "--json", *args],
                       capture_output=True, text=True)
    return r.returncode, (json.loads(r.stdout) if r.stdout.strip() else None), r.stderr


def age(repo, hours=48):
    """Backdate every worktree's admin files: the tool keeps a recently used one."""
    old = os.path.getmtime(repo / ".git") - hours * 3600
    for f in (repo / ".git" / "worktrees").rglob("*"):
        os.utime(f, (old, old))


def fixture(tmp_path):
    origin, repo, wts = tmp_path / "origin.git", tmp_path / "repo", tmp_path / "wt"
    git(tmp_path, "init", "-q", "--bare", str(origin))
    git(tmp_path, "init", "-q", "-b", "dev", str(repo))
    (repo / ".gitignore").write_text(".claude/\n")
    git(repo, "add", ".gitignore")
    commit(repo, "base")
    git(repo, "remote", "add", "origin", str(origin))
    for name in ("clean", "dirty", "unmerged", "unpushed"):
        git(repo, "worktree", "add", "-q", "-b", f"feat/{name}", str(wts / name))
        commit(wts / name, f"{name}.txt")
    for name in ("clean", "dirty", "unpushed"):
        git(repo, "merge", "-q", "--ff-only" if name == "clean" else "--no-ff", f"feat/{name}")
    git(repo, "push", "-q", "origin", "dev")
    (wts / "dirty" / "wip.txt").write_text("uncommitted")
    commit(wts / "unpushed", "after-land.txt")
    age(repo)
    return repo, wts


def test_dry_run_lists_exactly_the_merged_clean_worktree(tmp_path):
    repo, wts = fixture(tmp_path)
    rc, out, err = prune(repo)
    assert rc == 0, err
    assert [w["path"] for w in out["prunable"]] == [str((wts / "clean").resolve())]
    states = {pathlib.Path(w["path"]).name: w["state"] for w in out["worktrees"]}
    assert states == {"clean": "merged-clean", "dirty": "dirty",
                      "unmerged": "unmerged", "unpushed": "unmerged"}, states
    assert all((wts / n).is_dir() for n in states), "a dry run removed something"


def test_confirm_removes_only_that_one(tmp_path):
    repo, wts = fixture(tmp_path)
    rc, _, err = prune(repo, "--confirm")
    assert rc == 0, err
    assert not (wts / "clean").exists()
    assert all((wts / n).is_dir() for n in ("dirty", "unmerged", "unpushed"))
    assert (wts / "dirty" / "wip.txt").read_text() == "uncommitted"


def test_a_parent_holding_a_kept_child_is_kept(tmp_path):
    repo, wts = fixture(tmp_path)
    child = wts / "clean" / ".claude" / "worktrees" / "child"
    git(repo, "worktree", "add", "-q", "-b", "feat/child", str(child))
    commit(child, "child.txt")
    rc, out, err = prune(repo, "--confirm")
    assert rc == 0, err
    assert out["prunable"] == []
    assert (child / "child.txt").is_file(), "removing the parent took an unmerged child"


def test_unresolvable_base_is_unknown_not_empty(tmp_path):
    repo, _ = fixture(tmp_path)
    rc, out, _ = prune(repo, "--base", "origin/nope")
    assert rc == 0 and out["status"] == "UNKNOWN"
    assert prune(repo, "--base", "origin/nope", "--confirm")[0] == 2


def test_a_recently_used_worktree_is_kept(tmp_path):
    repo, wts = fixture(tmp_path)
    git(repo, "worktree", "add", "-q", "-b", "feat/fresh", str(wts / "fresh"), "dev")
    rc, out, err = prune(repo, "--confirm")
    assert rc == 0, err
    states = {pathlib.Path(w["path"]).name: w["state"] for w in out["worktrees"]}
    assert states["fresh"] == "recent", states
    assert (wts / "fresh").is_dir(), "a worktree a live session may use was removed"


def test_a_failed_child_removal_keeps_its_parent(tmp_path, monkeypatch):
    repo, wts = fixture(tmp_path)
    child = wts / "clean" / ".claude" / "worktrees" / "child"
    git(repo, "worktree", "add", "-q", "-b", "feat/child", str(child), "dev")
    age(repo)
    spec = importlib.util.spec_from_file_location("worktree_prune", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    real = mod.git

    def racing_git(cwd, *args):  # the child picks up work between scan and removal
        if args[:2] == ("worktree", "remove") and args[2] == str(child.resolve()):
            (child / "agent-wip.txt").write_text("uncommitted")
        return real(cwd, *args)

    monkeypatch.setattr(mod, "git", racing_git)
    monkeypatch.setattr(sys, "argv", ["worktree-prune.py", "--repo", str(repo), "--no-size", "--confirm"])
    assert mod.main() == 1
    assert (child / "agent-wip.txt").is_file(), "the parent's removal took the child's new work"
    assert (wts / "clean").is_dir()
