"""Anatomy gate: GitHub Actions integration jobs declare an explicit
timeout-minutes (2026-06-14).

A wet-test job with no `timeout-minutes` inherits GitHub's 6h (360-min)
default ceiling. A deployment hang — stack-up timeout (stack_up_wait_timeout
540s in all-on), GitLab cold init ~12min, an Authentik migration stall —
would then pin a hosted runner for SIX HOURS with zero operator visibility,
burning quota and stalling the release flow. The frozen-venv saga (2026-06-08)
cost ~21 CI cycles partly because hung jobs consume quota without clear
feedback.

A 45-min cap is adequate for the documented budget (~25min cold-blank
playbook + ~10min idempotence re-run + margin) yet collapses a hang from
6h to 45min. Pin both `integration` (macOS matrix) and `integration-linux`
(the gating Linux wet-test) so a future refactor can't silently drop the cap.
"""

from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
CI = REPO / ".github/workflows/ci.yml"

# Integration jobs are the only long-running wet-tests — the ones that can
# actually hang on a deployment stall. Other jobs (lint/syntax/pytest) are
# short and fail fast; they don't need the cap (though it wouldn't hurt).
INTEGRATION_JOBS = ("integration", "integration-linux")

# Upper sanity bound: the cap must be SHORT enough to be useful. 360 = the
# GitHub default we're guarding against; anything near it is no protection.
MAX_REASONABLE = 90


def _jobs() -> dict:
	data = yaml.safe_load(CI.read_text())
	assert isinstance(data, dict) and "jobs" in data, "ci.yml missing jobs map"
	return data["jobs"]


def test_ci_workflow_present_and_parses():
	assert CI.is_file(), ".github/workflows/ci.yml missing"
	jobs = _jobs()
	for job in INTEGRATION_JOBS:
		assert job in jobs, f"integration job '{job}' missing from ci.yml"


def test_integration_jobs_declare_timeout_minutes():
	"""Both integration jobs MUST set timeout-minutes — without it they
	inherit GitHub's 6h ceiling and a hung deploy pins a runner silently."""
	jobs = _jobs()
	for job in INTEGRATION_JOBS:
		spec = jobs[job]
		assert "timeout-minutes" in spec, (
			f"job '{job}' has no timeout-minutes — inherits GitHub's 6h "
			f"default; a deployment hang pins a runner for 6h"
		)


def test_integration_timeout_is_sane():
	"""The cap must be a positive int and well under the 6h default to
	actually bound a hang, while leaving room for the ~35min budget."""
	jobs = _jobs()
	for job in INTEGRATION_JOBS:
		val = jobs[job]["timeout-minutes"]
		assert isinstance(val, int), f"job '{job}' timeout-minutes not an int: {val!r}"
		assert 0 < val <= MAX_REASONABLE, (
			f"job '{job}' timeout-minutes={val} outside sane (0, {MAX_REASONABLE}] "
			f"range — too low starves the ~35min budget, too high doesn't bound a hang"
		)
