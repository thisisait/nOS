"""Anatomy gate: every lockfile we ship has a Dependabot entry for its ecosystem.

2026-10-07: four alerts (proxy-addr critical, source-map-js high x2,
postcss-selector-parser medium) sat open in face/ and cortex/ lockfiles.
dependabot.yml only listed `github-actions`, so Dependabot could ALERT but
never open the fix PR — the queue only drained when a human read red-status.

"Ship" means tracked by git: the walk used to be the filesystem, and went red
locally on gitignored test lockfiles and on lockfiles inside agent worktrees
(2026-10-11, 140 false entries), so the local suite disagreed with CI.
"""

from __future__ import annotations

import pathlib
import subprocess

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
DEPENDABOT = REPO / ".github/dependabot.yml"
ECOSYSTEMS = {"package-lock.json": "npm", "Cargo.lock": "cargo"}


def _lockfile_dirs(ecosystem: str) -> set[str]:
	names = [n for n, e in ECOSYSTEMS.items() if e == ecosystem]
	out = subprocess.run(["git", "-C", str(REPO), "ls-files", "-z", "--", *(f"*{n}" for n in names)],
	                     capture_output=True, text=True, check=True).stdout
	return {
		"/" + pathlib.PurePosixPath(p).parent.as_posix()
		for p in out.split("\0")
		if p and pathlib.PurePosixPath(p).name in names
		and "node_modules" not in p.split("/") and not p.startswith("state/fixtures/")
	}


def _covered(ecosystem: str) -> set[str]:
	cfg = yaml.safe_load(DEPENDABOT.read_text())
	return {u["directory"].rstrip("/") for u in cfg["updates"] if u["package-ecosystem"] == ecosystem}


def test_every_lockfile_has_an_update_entry():
	for ecosystem in sorted(set(ECOSYSTEMS.values())):
		missing = _lockfile_dirs(ecosystem) - _covered(ecosystem)
		assert not missing, (
			f"{ecosystem} lockfile without a Dependabot entry: {sorted(missing)} — "
			f"add `package-ecosystem: {ecosystem}` for each in .github/dependabot.yml"
		)


def test_the_walk_reads_git_not_the_disk():
	"""The shipped set: face, cortex and the thalamus workspace — never an ignored file."""
	assert _lockfile_dirs("npm") >= {"/files/anatomy/face", "/files/anatomy/cortex"}
	assert _lockfile_dirs("cargo") >= {"/files/anatomy/thalamus"}
	assert "/tests/e2e" not in _lockfile_dirs("npm"), "a gitignored lockfile was counted"
