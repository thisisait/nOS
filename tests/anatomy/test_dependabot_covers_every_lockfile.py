"""Anatomy gate: every npm lockfile we ship has a Dependabot `npm` entry.

2026-10-07: four alerts (proxy-addr critical, source-map-js high x2,
postcss-selector-parser medium) sat open in face/ and cortex/ lockfiles.
dependabot.yml only listed `github-actions`, so Dependabot could ALERT but
never open the fix PR — the queue only drained when a human read red-status.
"""

from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
DEPENDABOT = REPO / ".github/dependabot.yml"


def _lockfile_dirs() -> set[str]:
	return {
		"/" + p.parent.relative_to(REPO).as_posix()
		for p in REPO.rglob("package-lock.json")
		if "node_modules" not in p.parts and not p.is_relative_to(REPO / "state/fixtures")
	}


def test_every_lockfile_has_an_npm_update_entry():
	cfg = yaml.safe_load(DEPENDABOT.read_text())
	covered = {u["directory"].rstrip("/") for u in cfg["updates"] if u["package-ecosystem"] == "npm"}
	missing = _lockfile_dirs() - covered
	assert not missing, (
		f"package-lock.json without a Dependabot npm entry: {sorted(missing)} — "
		"add `package-ecosystem: npm` for each in .github/dependabot.yml"
	)
