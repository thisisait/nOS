"""The shared repo walk never reads a sibling worktree or node_modules.

MEASURED 2026-11-04: five gates walked REPO.rglob with no .claude/worktrees
exclusion, so a parallel wave's leftover checkouts changed their verdicts.
"""
from __future__ import annotations

from pathlib import Path

from _repo_walk import repo_files

PLANTED = ("a.j2", "a.md", "a.py")


def _plant(repo: Path) -> None:
    for d in ("roles/x", ".claude/worktrees/x/roles", "files/face/node_modules/p"):
        (repo / d).mkdir(parents=True)
        for name in PLANTED:
            (repo / d / name).write_text("x")
    (repo / ".claude/skills").mkdir(parents=True)
    (repo / ".claude/skills/s.md").write_text("x")


def _rel(repo: Path, pattern: str) -> set[str]:
    return {p.relative_to(repo).as_posix() for p in repo_files(repo, pattern)}


def test_the_walk_skips_sibling_worktrees_and_node_modules(tmp_path):
    _plant(tmp_path)
    for name in PLANTED:
        assert _rel(tmp_path, f"*{name[1:]}") - {".claude/skills/s.md"} == {f"roles/x/{name}"}
    assert ".claude/skills/s.md" in _rel(tmp_path, "*.md")


def test_the_walk_works_when_the_repo_is_itself_a_worktree(tmp_path):
    repo = tmp_path / "outer/.claude/worktrees/agent-y"
    _plant(repo)
    assert _rel(repo, "*.py") == {"roles/x/a.py"}


def test_extra_skip_dirs_prune_by_component(tmp_path):
    _plant(tmp_path)
    assert not list(repo_files(tmp_path, "*.py", skip={"roles"}))
