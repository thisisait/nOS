"""Anatomy gates for the git workflow doctrine (2026-05-17).

CLAUDE.md §Git Workflow + README.md §Contributing pin the three-tier
branch model (feat → dev → master) + the pzny local-cross-feature
branch + the pre-push hook that enforces both server-side rules
locally. These gates catch silent drift in the doctrine docs and the
hook script itself.
"""

from __future__ import annotations

import pathlib
import stat

REPO = pathlib.Path(__file__).resolve().parents[2]


def test_claude_md_describes_three_tier_branch_model():
	src = (REPO / "CLAUDE.md").read_text()
	# Three long-lived branches named explicitly.
	assert "`master`" in src and "`dev`" in src and "`pzny`" in src
	# Master is PR-only + locked on both remotes.
	assert "PR-only" in src
	assert "GitHub" in src and "Gitea" in src
	# The 2026-04-16 "never resurrect dev" rule is explicitly superseded.
	assert "superseded" in src.lower() or "no longer" in src.lower()


def test_readme_links_to_branch_model():
	src = (README := REPO / "README.md").read_text()
	# Short summary in Contributing.
	assert "feat/" in src and "dev" in src and "master" in src
	# Mentions the lock so contributors know direct push fails.
	assert "lock" in src.lower() or "protect" in src.lower()


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


def test_commit_convention_carries_subject_length_rule():
	"""The 50/72 rule must be in CLAUDE.md so every commit-authoring
	session (Claude included) honors it from the start of the
	conversation."""
	src = (REPO / "CLAUDE.md").read_text()
	assert "50 chars" in src.lower() or "≤ 50" in src or "<= 50" in src
