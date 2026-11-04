"""One repo walk for every file-scanning gate.

A raw REPO.rglob also reads sibling agent checkouts under .claude/worktrees/,
so a gate's verdict depended on which worktrees were lying about. Pruning is by
path RELATIVE to the root: a repo that itself sits in a worktree still walks.
"""
from __future__ import annotations

import fnmatch
import os
from pathlib import Path

ALWAYS_SKIP = frozenset({".git", "node_modules", ".ci-venv"})


def repo_files(root: Path, pattern: str = "*", skip=()):
    """Yield files under root whose name matches pattern, pruning skip dirs."""
    skip = ALWAYS_SKIP | set(skip)
    for dirpath, dirnames, filenames in os.walk(root):
        here = Path(dirpath)
        dirnames[:] = sorted(
            d for d in dirnames
            if d not in skip and not (d == "worktrees" and here.name == ".claude")
        )
        for name in sorted(filenames):
            if fnmatch.fnmatchcase(name, pattern):
                yield here / name
