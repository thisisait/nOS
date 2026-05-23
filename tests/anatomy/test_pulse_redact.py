"""Anatomy gate — Pulse stdout/stderr scrub (SEC-9, 2026-05-23).

Subprocess output forwarded by Pulse to Wing events can carry secrets
(env var dumps, CLI password flags, Bearer headers in tracebacks,
gitleaks-captured-secret previews). Without scrubbing, these persist
to wing.db.events → /audit timeline → host launchd.err.log.

`pulse.redact.scrub_text(s)` runs a small set of focused regexes that
target common secret shapes and replace the value with `<REDACTED>`,
preserving the labeled prefix so the operator still sees which key
was redacted.

This gate pins:
  * scrub_text function exists in pulse.redact module
  * Idempotent (double-application same as single)
  * Covers env-assignment / CLI-flag / Authorization-header / Bearer
  * daemon.py applies scrub_text to BOTH stdout_tail + stderr_tail
    before sending to Wing
"""

from __future__ import annotations

import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
PULSE_PKG = REPO / "files/anatomy/pulse"

# Make pulse module importable for runtime tests.
if str(PULSE_PKG) not in sys.path:
	sys.path.insert(0, str(PULSE_PKG))


def test_redact_module_present():
	assert (PULSE_PKG / "pulse/redact.py").is_file(), \
		"files/anatomy/pulse/pulse/redact.py missing — SEC-9 contract"


def test_scrub_text_redacts_env_assignments():
	from pulse.redact import scrub_text  # type: ignore[import-not-found]
	out = scrub_text("WING_API_TOKEN=kloFas7_pw_wing_api next")
	assert "kloFas7" not in out
	assert "<REDACTED>" in out
	assert "WING_API_TOKEN" in out, "must preserve the labeled prefix"


def test_scrub_text_redacts_cli_password_flags():
	"""Long-form flags only (--password, --token, …). Single-char `-p`
	intentionally NOT matched: too high false-positive risk (port,
	progress, etc.) — most operators use the long form in scripts."""
	from pulse.redact import scrub_text  # type: ignore[import-not-found]
	for line in (
		"--password=hunter2 ok",
		"--password hunter2 ok",
		"--token=abc123def456 next",
		"--bearer XXXyyyZZZ end",
		"--api-key abcdef123456 end",
	):
		out = scrub_text(line)
		assert "<REDACTED>" in out, f"CLI flag not scrubbed: {line!r} → {out!r}"


def test_scrub_text_redacts_http_authorization():
	from pulse.redact import scrub_text  # type: ignore[import-not-found]
	for line in (
		"Authorization: Bearer abc123def456ghi789",
		"Authorization: Basic dXNlcjpwYXNzd29yZA==",
		"Bearer abc123def456ghi789jkl context",
	):
		out = scrub_text(line)
		assert "<REDACTED>" in out, f"auth header not scrubbed: {line!r}"


def test_scrub_text_idempotent():
	from pulse.redact import scrub_text  # type: ignore[import-not-found]
	s = "WING_API_TOKEN=kloFas7_pw_a"
	first = scrub_text(s)
	twice = scrub_text(first)
	assert first == twice, f"scrub_text not idempotent: {first!r} vs {twice!r}"


def test_scrub_text_safe_on_empty_and_none():
	from pulse.redact import scrub_text  # type: ignore[import-not-found]
	assert scrub_text("") == ""
	assert scrub_text(None) == ""


def test_scrub_text_does_not_false_positive_on_paths():
	"""Legitimate diagnostic strings (file paths, ISO dates, URLs that
	don't carry secrets) MUST pass through unchanged. False positives
	make logs harder to read + may cause operators to disable scrub."""
	from pulse.redact import scrub_text  # type: ignore[import-not-found]
	for clean in (
		"normal log with /path/to/file.txt",
		"2026-05-23T10:30:00Z some event",
		"HTTP 200 /api/v1/hub/health 23ms",
		"docker exec mariadb-1 ls /var/lib/mysql",
	):
		assert scrub_text(clean) == clean, f"false positive on: {clean!r}"


def test_daemon_applies_scrub_before_posting():
	"""pulse/daemon.py must import the redact module + apply
	scrub_text to BOTH stdout_tail and stderr_tail before calling
	wing.post_run_finish."""
	src = (PULSE_PKG / "pulse/daemon.py").read_text()
	# Import.
	assert "from . import redact" in src or "from pulse import redact" in src, \
		"daemon.py must import the redact module"
	# Both tails must be scrubbed.
	assert "redact.scrub_text(result.stdout_tail)" in src, \
		"daemon.py must scrub_text(stdout_tail)"
	assert "redact.scrub_text(result.stderr_tail)" in src, \
		"daemon.py must scrub_text(stderr_tail)"
