"""Anatomy gate: the Devlog Pages workflow must not drift behind the main CI
workflow on shared GitHub-action versions.

pages.yml was authored new and never refreshed, so it lagged on
actions/checkout@v4 + setup-python@v5 while ci.yml had moved to @v6 — old
Node-runtime actions are a security/hygiene gap. This pins both workflows to
the SAME major for the shared actions, while leaving the Pages-specific
actions (upload-pages-artifact, deploy-pages) on their own tracks (no v6
exists for those).
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
PAGES = REPO / ".github/workflows/pages.yml"
CI = REPO / ".github/workflows/ci.yml"


def _uses(text: str, action: str) -> set[str]:
	"""Return the set of pinned major versions for `uses: <action>@vN`."""
	return set(re.findall(rf"uses:\s*{re.escape(action)}@(v\d+)", text))


def test_pages_workflow_present():
	assert PAGES.is_file(), "pages.yml missing"


def test_pages_checkout_matches_ci_major():
	"""Shared action — must track the same major as ci.yml (v6 today)."""
	pages = _uses(PAGES.read_text(), "actions/checkout")
	ci = _uses(CI.read_text(), "actions/checkout")
	assert pages, "pages.yml does not pin actions/checkout"
	assert pages == ci, (
		f"actions/checkout drift — pages.yml pins {pages}, ci.yml pins {ci}; "
		"keep them on the same major"
	)


def test_pages_setup_python_matches_ci_major():
	"""Shared action — must track the same major as ci.yml (v6 today)."""
	pages = _uses(PAGES.read_text(), "actions/setup-python")
	ci = _uses(CI.read_text(), "actions/setup-python")
	assert pages, "pages.yml does not pin actions/setup-python"
	assert pages == ci, (
		f"actions/setup-python drift — pages.yml pins {pages}, ci.yml pins {ci}; "
		"keep them on the same major"
	)


def test_pages_no_stale_shared_action_majors():
	"""Belt-and-suspenders: the specific stale majors that this gate was
	created to retire (checkout@v4, setup-python@v5) must not reappear."""
	text = PAGES.read_text()
	assert "actions/checkout@v4" not in text, "stale actions/checkout@v4 returned"
	assert "actions/setup-python@v5" not in text, "stale actions/setup-python@v5 returned"


def test_pages_specific_actions_unchanged():
	"""upload-pages-artifact + deploy-pages have no v6 — they stay on their
	own tracks. Pin them so a careless bump-everything sweep can't break the
	publish (deploy-pages@v5 / upload-pages-artifact@v4 don't exist today)."""
	text = PAGES.read_text()
	assert "actions/upload-pages-artifact@v3" in text
	assert "actions/deploy-pages@v4" in text
