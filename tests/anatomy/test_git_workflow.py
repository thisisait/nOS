"""Anatomy gates for the git workflow (2026-05-17): the pre-push hook.

The hook enforces the branch model (docs/git-and-release.md) locally: master
is PR-only, pzny goes to Gitea only. The CLAUDE.md/README phrase checks left
2026-11-09 (gate-diet): they pinned wording, not the hook.
"""

from __future__ import annotations

import pathlib
import stat

REPO = pathlib.Path(__file__).resolve().parents[2]


def test_pre_push_hook_present_and_executable():
	hook = REPO / "tools/git-hooks/pre-push"
	assert hook.is_file(), "pre-push hook missing"
	mode = hook.stat().st_mode
	assert mode & stat.S_IXUSR, "pre-push hook must be executable"


def test_pre_push_hook_refuses_master_direct_push():
	src = (REPO / "tools/git-hooks/pre-push").read_text()
	# Master case must exist with a non-zero exit.
	assert "master)" in src
	assert "exit 1" in src


def test_pre_push_hook_isolates_pzny_to_gitea():
	src = (REPO / "tools/git-hooks/pre-push").read_text()
	# pzny case checks the remote name explicitly.
	assert "pzny)" in src
	assert '"$remote" != "gitea"' in src
