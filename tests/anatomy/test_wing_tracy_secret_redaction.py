"""Anatomy gate — Wing's Tracy debugger redacts secrets in exception
dumps (SEC-2, 2026-05-23).

Pre-SEC-2 incident: ~/wing/app/log/exception--*.html files (created by
Tracy on any unhandled PHP exception) dumped the full
EnvironmentVariables block — including WING_API_TOKEN, BONE_SECRET,
AUTHENTIK_BOOTSTRAP_TOKEN, INFISICAL_API_TOKEN, STALWART_ADMIN_PASSWORD,
NOS_DEPLOY_HMAC_SECRET, WING_EVENTS_HMAC_SECRET. The files were mode
0644 (world-readable to local UIDs).

Two layers of defense:
  1. Tracy `$keysToHide` extended to mask values for nOS-specific
     env key substrings (token, secret, key, hmac, jwt, bearer, …)
     in addition to Tracy's stock list (password, authorization,
     php-auth-pw).
  2. Wing log dir provisioned at mode 0700 by the role.

This gate pins both layers.
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]


def test_booting_php_extends_tracy_keys_to_hide():
	"""Booting.php must extend Tracy\\Debugger::$keysToHide with the
	nOS secret-name substring list AFTER enableTracy() registers the
	debugger. Tracy reads $keysToHide at dump time, not register time —
	so the assignment can happen after enableTracy."""
	src = (REPO / "files/anatomy/wing/app/Bootstrap/Booting.php").read_text()
	# Must use Tracy\Debugger.
	assert "use Tracy\\Debugger;" in src
	# Must extend the existing list (NOT overwrite — Tracy's stock list
	# contains useful defaults like 'password' that we don't want to drop).
	assert "Debugger::$keysToHide = array_merge(" in src
	# Must reference a class-level constant or method so the list is
	# centralized + reviewable.
	assert "SECRET_KEY_SUBSTRINGS" in src or "secretKeySubstrings()" in src
	# The list must contain at minimum the nOS-specific anatomy keys.
	required_substrings = [
		'token', 'secret', 'hmac', 'jwt', 'bearer',
		'key',          # APP_KEY, NOS_DEPLOY_HMAC_SECRET
		'credentials',
	]
	for s in required_substrings:
		assert f"'{s}'" in src, \
			f"Booting.php SECRET_KEY_SUBSTRINGS must include '{s}' substring"


def test_booting_extends_after_enable_tracy():
	"""The order matters narrowly: enableTracy() must register the
	debugger BEFORE we assign $keysToHide. Reversed order would assign
	to a stale class default."""
	src = (REPO / "files/anatomy/wing/app/Bootstrap/Booting.php").read_text()
	enable_idx = src.find("enableTracy(")
	extend_idx = src.find("Debugger::$keysToHide = array_merge")
	assert enable_idx > 0 and extend_idx > 0
	assert extend_idx > enable_idx, \
		"$keysToHide assignment must come AFTER enableTracy() call"


def test_wing_role_creates_log_dir_at_0700():
	"""Even with Tracy redaction, the log directory's mode determines
	who can READ the exception dumps. Was 0755 (default of the shared
	0755 loop in pazny.wing/tasks/main.yml). Must be 0700."""
	src = (REPO / "roles/pazny.wing/tasks/main.yml").read_text()
	# Find a dedicated task that explicitly sets wing_log_dir to 0700.
	idx = src.find("Ensure log directory exists at 0700")
	assert idx > 0, \
		"pazny.wing must have a dedicated task setting wing_log_dir to 0700"
	# The 0755 loop must NOT include wing_log_dir anymore.
	loop_start = src.find("Ensure runtime directories exist")
	loop_end = src.find("\n- name:", loop_start + 10)
	loop_body = src[loop_start:loop_end]
	# wing_log_dir line MUST NOT be inside the 0755 loop block.
	assert "{{ wing_log_dir }}" not in loop_body, \
		"wing_log_dir must be removed from the 0755 loop (use the dedicated 0700 task)"
