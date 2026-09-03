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
	"""The pages pair moves on its own track. Pinned so a bump-everything
	sweep is forced through this gate — which fired 2026-09-03 exactly as
	designed: Dependabot #26 attested upload-pages-artifact@v5 and
	deploy-pages@v5 exist, and the bump landed deliberately (ae8024db)."""
	text = PAGES.read_text()
	assert "actions/upload-pages-artifact@v5" in text
	assert "actions/deploy-pages@v5" in text


# --- release-artifact gate (no-release-artifact-validation-gate) -------------
# The devlog-release.sh pre-flight is operator-gated and can be bypassed by a
# hand-cut tag. pages.yml fires on every `v*` tag push, so it must re-validate
# the release artifacts (git tag, devlog `release:` entry, RELEASE.md section)
# AFTER the tag lands and gate the publish (build) on them.


def _job_block(text: str, job: str) -> str:
	"""Return the YAML lines belonging to top-level job `job` (until the next
	top-level job, which is indented exactly 2 spaces)."""
	lines = text.splitlines()
	start = None
	for i, ln in enumerate(lines):
		if re.match(rf"^  {re.escape(job)}:\s*$", ln):
			start = i
			break
	assert start is not None, f"pages.yml has no '{job}:' job"
	end = len(lines)
	for j in range(start + 1, len(lines)):
		if re.match(r"^  \S+:\s*$", lines[j]):
			end = j
			break
	return "\n".join(lines[start:end])


def test_pages_has_release_validate_job():
	"""A dedicated validate job must exist to gate the publish."""
	text = PAGES.read_text()
	assert re.search(r"^  validate:\s*$", text, re.MULTILINE), \
		"pages.yml has no 'validate:' job — the release-artifact gate is gone"


def test_pages_build_needs_validate():
	"""The publish (build) must be gated behind validate — without `needs`,
	an incomplete release still reaches GitHub Pages."""
	build = _job_block(PAGES.read_text(), "build")
	assert re.search(r"^\s*needs:\s*validate\s*$", build, re.MULTILINE), \
		"build job does not declare `needs: validate` — publish is ungated"


def test_pages_validate_checks_all_three_artifacts():
	"""The gate must validate the git tag, the devlog `release:` entry, and the
	RELEASE.md section — the three artifacts devlog-release.sh pre-flights."""
	validate = _job_block(PAGES.read_text(), "validate")
	# (1) git tag presence
	assert "refs/tags/$TAG" in validate, "validate does not check the git tag"
	# (2) devlog release entry
	assert "release: $TAG" in validate, \
		"validate does not check for a devlog 'release: <tag>' entry"
	# (3) RELEASE.md section
	assert "RELEASE.md" in validate and "## $TAG" in validate, \
		"validate does not check the RELEASE.md '## <tag>' section"


def test_pages_validate_runs_on_tag_pushes():
	"""The gate is only meaningful on tag pushes — pages.yml must still trigger
	on `v*` tags (otherwise the validate job never fires)."""
	text = PAGES.read_text()
	assert re.search(r"tags:\s*\['v\*'\]", text) or "tags: ['v*']" in text, \
		"pages.yml no longer triggers on v* tag pushes"
