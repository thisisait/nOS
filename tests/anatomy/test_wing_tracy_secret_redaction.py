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

plat-gate-shape (2026-09-15): a whole-file substring hunt stayed GREEN
after the `$keysToHide` merge AND the `hash_equals` cookie gate were
commented out (debug forced ON). Comments are not the redaction list.
Read comment-stripped PHP / XML and parse the constant.
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
BOOTING = REPO / "files/anatomy/wing/app/Bootstrap/Booting.php"
PLIST = REPO / "roles/pazny.wing/templates/wing.plist.j2"

_PHP_BLOCK = re.compile(r"/\*.*?\*/", re.S)
_PHP_LINE = re.compile(r"//[^\n]*")
_XML_COMMENT = re.compile(r"<!--.*?-->", re.S)

REQUIRED_SUBSTRINGS = (
	"token",
	"secret",
	"hmac",
	"jwt",
	"bearer",
	"key",  # APP_KEY, NOS_DEPLOY_HMAC_SECRET
	"credentials",
)


def _php_code(src: str) -> str:
	return _PHP_LINE.sub("", _PHP_BLOCK.sub("", src))


def _xml_code(src: str) -> str:
	return _XML_COMMENT.sub("", src)


def _booting_code() -> str:
	return _php_code(BOOTING.read_text())


def _secret_key_substrings(code: str) -> list[str]:
	m = re.search(r"SECRET_KEY_SUBSTRINGS\s*=\s*\[(.*?)]\s*;", code, re.S)
	assert m, "SECRET_KEY_SUBSTRINGS array not found in live PHP"
	return re.findall(r"'([^']+)'", m.group(1))


def test_booting_php_extends_tracy_keys_to_hide():
	"""Booting.php must extend Tracy\\Debugger::$keysToHide with the
	nOS secret-name substring list AFTER enableTracy() registers the
	debugger. Tracy reads $keysToHide at dump time, not register time —
	so the assignment can happen after enableTracy."""
	code = _booting_code()
	assert re.search(r"use\s+Tracy\\Debugger\s*;", code)
	# Extend the existing list (NOT overwrite — Tracy's stock list
	# contains useful defaults like 'password' that we don't want to drop).
	assert re.search(
		r"Debugger::\$keysToHide\s*=\s*array_merge\s*\(\s*Debugger::\$keysToHide",
		code,
	), "must array_merge into Debugger::$keysToHide, not overwrite it"
	items = _secret_key_substrings(code)
	missing = [s for s in REQUIRED_SUBSTRINGS if s not in items]
	assert not missing, (
		f"SECRET_KEY_SUBSTRINGS is missing {missing} — parsed {items}"
	)


def test_booting_extends_after_enable_tracy():
	"""The order matters narrowly: enableTracy() must register the
	debugger BEFORE we assign $keysToHide. Reversed order would assign
	to a stale class default."""
	code = _booting_code()
	enable_idx = code.find("enableTracy(")
	extend = re.search(r"Debugger::\$keysToHide\s*=\s*array_merge", code)
	assert enable_idx > 0 and extend, "enableTracy() or $keysToHide merge missing"
	assert extend.start() > enable_idx, (
		"$keysToHide assignment must come AFTER enableTracy() call"
	)


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
	code = _booting_code()
	assert "setDebugMode('127.0.0.1')" not in code, "IP gating is a no-op behind the loopback proxy"
	assert re.search(r"getenv\(\s*'WING_TRACY_SECRET'\s*\)", code), (
		"debug must read WING_TRACY_SECRET from the environment"
	)
	assert re.search(r"\$_COOKIE\s*\[\s*'tracy-debug'\s*\]", code), (
		"debug must require a matching tracy-debug cookie"
	)
	assert re.search(r"hash_equals\s*\(", code), "cookie compare must be constant-time"
	# The plist must surface the env (empty default = debug never on).
	plist = _xml_code(PLIST.read_text())
	assert "<key>WING_TRACY_SECRET</key>" in plist, (
		"plist must declare WING_TRACY_SECRET as a live env key, not a comment"
	)
	assert "wing_tracy_secret | default('')" in plist


def test_error_presenter_renders_clean_production_page():
	"""common.neon sets `errorPresenter: Error`; the class was missing (masked
	by always-on debug), so production errors fell back to Tracy's generic
	page (leaks <meta generator=Tracy>). A minimal ErrorPresenter must exist,
	implement IPresenter directly (NOT BasePresenter — else the edge guard
	re-fires during error handling), and emit no Tracy generator."""
	ep = REPO / "files/anatomy/wing/app/Presenters/ErrorPresenter.php"
	assert ep.is_file(), "ErrorPresenter.php missing (errorPresenter: Error in common.neon)"
	src = _php_code(ep.read_text())
	assert "implements Nette\\Application\\IPresenter" in src, "must implement IPresenter directly"
	assert "extends BasePresenter" not in src, "must NOT extend BasePresenter (edge guard would re-fire)"
	# The rendered page must not emit a framework generator meta (the Tracy
	# fallback's leak). Guard the actual HTML markers, not the docstring.
	assert 'name="generator"' not in src and 'content="Tracy"' not in src, \
		"clean error page must not emit a generator/Tracy meta"
