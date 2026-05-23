"""Pulse stdout/stderr scrub (SEC-9, 2026-05-23).

Subprocess output captured by Pulse runners can carry secrets:
  - `WING_API_TOKEN=kloFas7_...` env dumped by a misconfigured script
  - `mariadb-upgrade --password=...` error context
  - `Bearer <token>` from an HTTP client traceback
  - `Authorization: Basic <b64>` from a curl error message
  - gitleaks' own "Captured" preview blocks

Forwarding the raw tails to Wing → events → /audit timeline → host
launchd.err.log persists those values in plain text in places the
operator and any local UID can read. Pulse-runner-driven agents
inherit the full operator UID env, so this is a real exfil class.

`scrub_text(s)` applies a small set of focused regexes that target the
shapes above and replaces the secret portion with `<REDACTED>`. The
goal is high recall on actually-secret patterns, low false-positive
rate on legitimate diagnostic output (URLs, file paths, ISO dates).

Used by:
  - `pulse/daemon.py::_run_job_async` on `result.stderr_tail` +
    `result.stdout_tail` before they go to Wing.
"""

from __future__ import annotations

import re


# Env-var assignment shape: `<KEY>=<value>` or `<KEY>: <value>` where
# KEY contains any of: TOKEN, SECRET, PASSWORD, KEY, HMAC, JWT, BEARER,
# CREDENTIAL, AUTH, COOKIE. Value can be quoted or bare; we capture up
# to whitespace or the next shell-meta.
_ENV_ASSIGNMENT = re.compile(
	r"(?P<prefix>\b[A-Z][A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|KEY|HMAC|JWT|BEARER|CREDENTIAL|AUTH|COOKIE)[A-Z0-9_]*\s*[:=]\s*)"
	r"['\"]?(?P<value>[A-Za-z0-9+/=_.\-]{6,256})['\"]?",
	re.IGNORECASE,
)

# CLI password flags: `--password=X`, `--password X`, `-p X`. The first
# group is the flag; everything after is the secret value up to the
# next whitespace.
_CLI_PASSWORD_FLAG = re.compile(
	r"(--?(?:password|pass|pwd|token|secret|api[-_]?key|bearer)(?:[ =])"
	r")(?P<value>[^\s]+)",
	re.IGNORECASE,
)

# HTTP Authorization header values: `Authorization: Basic <b64>` /
# `Bearer <token>`. Match anywhere in the line, redact the token.
_HTTP_AUTH_HEADER = re.compile(
	r"(?P<prefix>Authorization\s*:\s*(?:Bearer|Basic|Digest)\s+)(?P<value>[A-Za-z0-9+/=_.\-]{8,512})",
	re.IGNORECASE,
)

# `Bearer <token>` standalone (not in Authorization: header — appears in
# tracebacks, log lines).
_BEARER_INLINE = re.compile(
	r"(?P<prefix>\bBearer\s+)(?P<value>[A-Za-z0-9+/=_.\-]{16,512})\b",
)


def scrub_text(s: str | None) -> str:
	"""Return a copy of ``s`` with secret-shaped substrings replaced
	with ``<REDACTED>``. Idempotent: applying twice yields the same
	output as applying once.

	Empty / None input returns empty string.
	"""
	if not s:
		return ""
	text = str(s)
	# Apply patterns in deterministic order. Each pattern preserves
	# the labeled prefix so the operator still sees WHICH key was
	# redacted (e.g. "WING_API_TOKEN=<REDACTED>" vs just <REDACTED>).
	text = _ENV_ASSIGNMENT.sub(lambda m: m.group("prefix") + "<REDACTED>", text)
	text = _CLI_PASSWORD_FLAG.sub(lambda m: m.group(1) + "<REDACTED>", text)
	text = _HTTP_AUTH_HEADER.sub(lambda m: m.group("prefix") + "<REDACTED>", text)
	text = _BEARER_INLINE.sub(lambda m: m.group("prefix") + "<REDACTED>", text)
	return text
