"""Anatomy gates for tools/nos-push + Gitea mirror_interval default
(A17, 2026-05-20).

`tools/nos-push` is a wrapper around `git push` that triggers Gitea
mirror-sync via API immediately after a successful push. Eliminates the
10-minute mirror poll delay → near-zero latency between `git push` and
the Woodpecker pipeline firing.

Also pins:
  * Gitea mirror_interval default = 1m (was 10m) as a safety net for raw
    `git push` (operators who don't yet use the wrapper)
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


def test_gitea_default_mirror_interval_is_under_two_minutes():
	"""Default poll interval must be tight enough that raw `git push`
	(without the wrapper) doesn't sit for 10 minutes. 1m is the chosen
	sweet spot."""
	src = (REPO / "roles/pazny.gitea/defaults/main.yml").read_text()
	m = re.search(r'gitea_nos_repo_mirror_interval:\s*"([^"]+)"', src)
	assert m, "gitea_nos_repo_mirror_interval default not declared"
	value = m.group(1)
	# Acceptable: 30s, 1m0s, 60s — anything ≤ 120 seconds.
	# Sanity-parse: <N>m<N>s OR <N>s
	mm = re.match(r'^(\d+)m(\d+)s$', value)
	ss = re.match(r'^(\d+)s$', value)
	if mm:
		seconds = int(mm.group(1)) * 60 + int(mm.group(2))
	elif ss:
		seconds = int(ss.group(1))
	else:
		assert False, f"unrecognized interval format: {value}"
	assert seconds <= 120, (
		f"gitea_nos_repo_mirror_interval={value} ({seconds}s) is too long "
		"— raw `git push` will sit for that long before Woodpecker sees "
		"the commit. Set to ≤ 1m to keep the fallback poll responsive."
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
