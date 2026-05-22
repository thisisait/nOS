"""Anatomy gates for tools/nos-push + Gitea mirror_interval default
(A17, 2026-05-20).

`tools/nos-push` is a wrapper around `git push` that triggers Gitea
mirror-sync via API immediately after a successful push. Eliminates the
10-minute mirror poll delay → near-zero latency between `git push` and
the Woodpecker pipeline firing.

Also pins:
  * Gitea mirror_interval default = 10m0s — Gitea's server-side
    [mirror].MIN_INTERVAL floor (configurable in app.ini but defaulting
    to 10m). The 2026-05-21 attempt to set 1m0s came back HTTP 422 from
    the PATCH API. The fast path is the wrapper (instant /mirror-sync);
    the per-repo interval is the safety net for raw-push users.
  * The post-repo task reconverges the per-repo mirror_interval via
    PATCH on every playbook run (so a default-value bump propagates to
    existing installs)
"""

from __future__ import annotations

import pathlib
import re
import stat
import subprocess

REPO = pathlib.Path(__file__).resolve().parents[2]


# ── tools/nos-push wrapper ───────────────────────────────────────────────


def test_nos_push_wrapper_present_and_executable():
	p = REPO / "tools/nos-push"
	assert p.is_file(), "tools/nos-push missing"
	mode = p.stat().st_mode
	assert mode & stat.S_IXUSR, "tools/nos-push must be executable"


def test_nos_push_bash_syntax_clean():
	p = REPO / "tools/nos-push"
	result = subprocess.run(["bash", "-n", str(p)], capture_output=True, text=True)
	assert result.returncode == 0, f"bash -n failed: {result.stderr}"


def test_nos_push_does_not_skip_underlying_push():
	"""Even with --skip-sync, the real `git push` MUST still run. A
	wrapper that silently no-ops on errors would be worse than no
	wrapper."""
	src = (REPO / "tools/nos-push").read_text()
	# The git push command appears BEFORE any SKIP_SYNC short-circuit.
	push_pos = src.find('git -C "$REPO_DIR" push')
	skip_check = src.find('SKIP_SYNC" -eq 1 ')
	assert 0 < push_pos < skip_check, (
		"nos-push must `git push` before the --skip-sync gate so the "
		"primary action still happens regardless of flags"
	)


def test_nos_push_handles_empty_args_array():
	"""Empty GIT_ARGS array must NOT expand to a literal '' that git
	rejects as 'bad repository'. Pinned after the 2026-05-20 first
	live-test regression where `nos-push --skip-sync` (no other args)
	fell into `git push ''`. Fix: branch on array length."""
	src = (REPO / "tools/nos-push").read_text()
	# Look for the array-length branch — either form is acceptable.
	assert ('${#GIT_ARGS[@]}' in src and '-gt 0' in src), (
		"nos-push must branch on `${#GIT_ARGS[@]}` to avoid empty-array "
		"expansion producing literal '' arg to git push"
	)


def test_nos_push_handles_missing_token_gracefully():
	"""Operator's first push might happen before gitea_api_token is
	provisioned. Wrapper must NOT fail in that case — push still
	succeeds, mirror-sync is just skipped with a one-line warning."""
	src = (REPO / "tools/nos-push").read_text()
	assert 'mirror-sync skipped: missing' in src
	assert "exit 0" in src  # graceful exit on missing token


def test_nos_push_uses_short_timeout():
	"""curl call MUST timeout fast (≤5s) so a slow/unreachable Gitea
	doesn't block the push wrapper for minutes."""
	src = (REPO / "tools/nos-push").read_text()
	assert re.search(r"--max-time\s+[1-5]\b", src), \
		"nos-push curl call needs --max-time ≤ 5s"


# ── Gitea mirror_interval default ────────────────────────────────────────


def test_gitea_default_mirror_interval_at_server_floor():
	"""Gitea hard-codes [mirror].MIN_INTERVAL = 10m in app.ini; per-repo
	overrides below that come back HTTP 422 from the PATCH API (operator
	blank crash 2026-05-21: 'invalid mirror interval: 1m0s is below
	minimum interval: 10m0s'). So 10m0s is the floor for the per-repo
	override. Instant sync is owned by tools/nos-push's /mirror-sync
	call — the per-repo interval is purely a safety net for raw
	`git push` users.

	Pin EXACTLY 10m0s (not >10m0s) so operators don't drift to longer
	fallbacks that defeat the safety net. To lower the floor globally,
	patch app.ini's [mirror].MIN_INTERVAL — out of scope for this gate."""
	src = (REPO / "roles/pazny.gitea/defaults/main.yml").read_text()
	m = re.search(r'^gitea_nos_repo_mirror_interval:\s*"([^"]+)"', src, re.MULTILINE)
	assert m, "gitea_nos_repo_mirror_interval default not declared"
	assert m.group(1) == "10m0s", (
		f"gitea_nos_repo_mirror_interval={m.group(1)} — Gitea's MIN_INTERVAL "
		"floor is 10m0s; anything lower returns HTTP 422 from the PATCH API."
	)


def test_gitea_post_repo_patches_mirror_interval_on_existing_repo():
	"""Bump the default value, and existing repos must pick it up on
	next playbook run without manual operator intervention. The PATCH
	task pins this."""
	src = (REPO / "roles/pazny.gitea/tasks/post-repo.yml").read_text()
	assert "Reconverge mirror_interval" in src
	assert "method: PATCH" in src
	# Must run only when repo already exists (check.status == 200).
	assert "_gitea_repo_check.status == 200" in src
