"""Anatomy gates for the A17 CI deploy-trigger (2026-05-20).

Pipeline → Wing /api/v1/deploy-trigger → `ansible-playbook` subprocess
on the host. Security model:

  1. HMAC validation (NOS_DEPLOY_HMAC_SECRET) — only Woodpecker can
     trigger; ±5-min timestamp window blocks replay.
  2. branch allowlist (dev / pzny only) — master is operator-manual.
  3. tag allowlist — only roles that DO NOT need sudo are accepted.
     This is the hard line between auto-deploy and operator-only.
  4. UUID format check — deploy_uuid must be a UUID4 (mappable to log).
  5. Concurrency lock in tools/deploy-from-ci.sh.

These gates pin each layer of the defense-in-depth so a future refactor
that drops one of them fails CI rather than silently widening the blast
radius of a compromised pipeline.
"""

from __future__ import annotations

import pathlib
import re
import stat
import subprocess

REPO = pathlib.Path(__file__).resolve().parents[2]
PRESENTER = REPO / "files/anatomy/wing/app/Presenters/Api/DeployTriggerPresenter.php"
WRAPPER = REPO / "tools/deploy-from-ci.sh"
WOODPECKER = REPO / ".woodpecker.yml"


# ── Wing presenter ──────────────────────────────────────────────────────


def test_deploy_trigger_presenter_present():
	assert PRESENTER.is_file()


def test_deploy_trigger_presenter_php_syntax_clean():
	r = subprocess.run(["php", "-l", str(PRESENTER)], capture_output=True, text=True)
	assert r.returncode == 0, r.stderr


def test_deploy_trigger_endpoint_is_post_only():
	src = PRESENTER.read_text()
	assert "requireMethod('POST')" in src


def test_deploy_trigger_endpoint_validates_hmac():
	src = PRESENTER.read_text()
	assert "verifyHmac" in src
	assert "hash_hmac('sha256'" in src
	assert "hash_equals" in src
	assert "NOS_DEPLOY_HMAC_SECRET" in src


def test_deploy_trigger_endpoint_clamps_timestamp_window():
	"""HMAC window must be tight (≤ 5 min) so a captured signature
	can't be replayed days later. Pinned at 300 seconds."""
	src = PRESENTER.read_text()
	assert "HMAC_WINDOW_SECONDS = 300" in src


def test_deploy_trigger_branch_allowlist():
	"""master is OPERATOR-MANUAL — auto-deploy must refuse it. Only
	dev + pzny are allowed."""
	src = PRESENTER.read_text()
	m = re.search(r"ALLOWED_BRANCHES\s*=\s*\[([^\]]+)\]", src)
	assert m, "ALLOWED_BRANCHES list not declared"
	allowed = m.group(1)
	assert "'dev'" in allowed
	assert "'pzny'" in allowed
	assert "'master'" not in allowed
	assert "'main'" not in allowed


def test_deploy_trigger_rejects_sudo_tags():
	"""Tags that need sudo (homebrew, mac.*, autostart) MUST NOT be in
	the allowlist — a compromised CI runner could otherwise get the
	playbook to install homebrew packages, modify macOS prefs, etc."""
	src = PRESENTER.read_text()
	# Find the ALLOWED_TAGS array (anchored by the constant name).
	start = src.find("ALLOWED_TAGS = [")
	end = src.find("];", start)
	assert start > 0 and end > start
	allowed_block = src[start:end]
	for forbidden in ("homebrew", "dotfiles", "mac.dock", "mac.mas",
	                  "mac.homebrew", "autostart", "ssh", "iiab-terminal",
	                  "secrets"):
		# Use single-quote check to avoid matching commentary.
		assert f"'{forbidden}'" not in allowed_block, (
			f"tag {forbidden!r} is in ALLOWED_TAGS — would let CI "
			f"runner escalate to sudo-requiring tasks"
		)


def test_deploy_trigger_validates_uuid_format():
	"""Operator should be able to locate a deploy by UUID in
	~/.nos/deploys/<uuid>.log. Free-form ids break that contract."""
	src = PRESENTER.read_text()
	assert re.search(
		r'preg_match\(.*\[a-f0-9\]\{8\}-\[a-f0-9\]\{4\}-\[a-f0-9\]\{4\}-\[a-f0-9\]\{4\}-\[a-f0-9\]\{12\}',
		src,
	), "deploy_uuid format not UUID4-validated"


def test_deploy_trigger_uses_escapeshellarg():
	"""All subprocess args must be escapeshellarg'd. Without it, a
	compromised CI runner could inject shell metacharacters."""
	src = PRESENTER.read_text()
	# escapeshellarg appears at least 3x (script path, uuid, tag list)
	assert src.count("escapeshellarg(") >= 3


def test_deploy_trigger_route_mounted():
	src = (REPO / "files/anatomy/wing/app/Core/RouterFactory.php").read_text()
	assert "'api/v1/deploy-trigger', 'DeployTrigger:default'" in src


# ── Host-side wrapper ────────────────────────────────────────────────────


def test_deploy_wrapper_present_and_executable():
	assert WRAPPER.is_file()
	mode = WRAPPER.stat().st_mode
	assert mode & stat.S_IXUSR


def test_deploy_wrapper_bash_syntax_clean():
	r = subprocess.run(["bash", "-n", str(WRAPPER)], capture_output=True, text=True)
	assert r.returncode == 0, r.stderr


def test_deploy_wrapper_runs_ansible_playbook():
	src = WRAPPER.read_text()
	assert "ansible-playbook main.yml" in src
	assert "--tags" in src


def test_deploy_wrapper_has_concurrency_lock():
	"""Without a lock, two simultaneous triggers could race on shared
	state (compose stack, wing daemon restart). flock OR mkdir-lock
	must be present."""
	src = WRAPPER.read_text()
	assert "flock" in src or "LOCK_DIR" in src


def test_deploy_wrapper_logs_to_uuid_path():
	src = WRAPPER.read_text()
	assert "LOG_FILE=\"$LOG_DIR/${DEPLOY_UUID}.log\"" in src


def test_deploy_wrapper_sends_completion_notification():
	src = WRAPPER.read_text()
	assert "_notify" in src
	assert "/api/v1/notifications" in src
	# Different severities for success vs failure
	assert '_notify "info"' in src
	assert '_notify "high"' in src


# ── Woodpecker pipeline integration ─────────────────────────────────────


def test_woodpecker_pipeline_has_deploy_trigger_step():
	src = WOODPECKER.read_text()
	assert "deploy-trigger:" in src
	# Gated on dev branch only
	assert "branch: dev" in src
	# Uses secrets, not hardcoded URL/secret
	assert "from_secret: wing_deploy_url" in src
	assert "from_secret: nos_deploy_hmac_secret" in src


def test_woodpecker_deploy_step_uses_deploy_tags_footer():
	"""Commit messages can opt into deploy via `deploy-tags: a,b,c`
	footer. No footer = no deploy (safe default)."""
	src = WOODPECKER.read_text()
	assert "deploy-tags:" in src


def test_woodpecker_deploy_step_skips_on_no_footer():
	"""If the footer is empty, the step exits 0 (no deploy) instead of
	failing the pipeline. Otherwise every non-deploy commit (docs,
	tests, etc.) would fail CI."""
	src = WOODPECKER.read_text()
	assert "no deploy-tags footer" in src
	assert "exit 0" in src


# ── Wing env wiring ─────────────────────────────────────────────────────


def test_wing_plist_carries_deploy_hmac_secret():
	src = (REPO / "roles/pazny.wing/templates/wing.plist.j2").read_text()
	assert "NOS_DEPLOY_HMAC_SECRET" in src
	assert "nos_deploy_hmac_secret" in src
	assert "NOS_DEPLOY_LOG_DIR" in src
