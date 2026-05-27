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


def test_tracy_debug_off_by_default_cookie_gated():
	"""2026-05-27: setDebugMode('127.0.0.1') kept the Tracy bar ON for ALL
	traffic — Wing binds loopback so Traefik proxies every request from
	127.0.0.1 (CF-proxied users included), leaking $_COOKIE/config/SQL dumps.
	Debug must be OFF by default and gated behind a long secret cookie."""
	src = (REPO / "files/anatomy/wing/app/Bootstrap/Booting.php").read_text()
	assert "setDebugMode('127.0.0.1')" not in src, "IP gating is a no-op behind the loopback proxy"
	assert "WING_TRACY_SECRET" in src, "debug must be gated on the WING_TRACY_SECRET env"
	assert "tracy-debug" in src, "debug must require a matching tracy-debug cookie"
	assert "hash_equals(" in src, "cookie compare must be constant-time"
	# The plist must surface the env (empty default = debug never on).
	plist = (REPO / "roles/pazny.wing/templates/wing.plist.j2").read_text()
	assert "WING_TRACY_SECRET" in plist and "wing_tracy_secret | default('')" in plist


def test_error_presenter_renders_clean_production_page():
	"""common.neon sets `errorPresenter: Error`; the class was missing (masked
	by always-on debug), so production errors fell back to Tracy's generic
	page (leaks <meta generator=Tracy>). A minimal ErrorPresenter must exist,
	implement IPresenter directly (NOT BasePresenter — else the edge guard
	re-fires during error handling), and emit no Tracy generator."""
	ep = REPO / "files/anatomy/wing/app/Presenters/ErrorPresenter.php"
	assert ep.is_file(), "ErrorPresenter.php missing (errorPresenter: Error in common.neon)"
	src = ep.read_text()
	assert "implements Nette\\Application\\IPresenter" in src, "must implement IPresenter directly"
	assert "extends BasePresenter" not in src, "must NOT extend BasePresenter (edge guard would re-fire)"
	# The rendered page must not emit a framework generator meta (the Tracy
	# fallback's leak). Guard the actual HTML markers, not the docstring.
	assert 'name="generator"' not in src and 'content="Tracy"' not in src, \
		"clean error page must not emit a generator/Tracy meta"
