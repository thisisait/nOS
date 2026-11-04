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


# `<KEY>=<value>` / `<KEY>: <value>`. A long keyword may sit anywhere in KEY (TOKEN=, XTOKEN=);
# KEY and AUTH must end a `_` segment (PRIVATEKEY, privateKey, OAUTH; not KEYCLOAK_, GIT_AUTHOR_),
# MONKEY and SORT_KEY excepted. Quoted values run to the quote, `=` values to whitespace, `:` values
# to end of line, so `Primary key: users_pkey` hides too: diagnostics lose, secrets never leak.
_ENV_ASSIGNMENT = re.compile(
	r"(?P<prefix>\b(?=[A-Z])"
	r"(?=[A-Z0-9_]*?(?:TOKEN|SECRET|PASSWORD|PASSWD|APIKEY|HMAC|JWT|BEARER|CREDENTIAL|COOKIE"
	r"|(?<!MON)(?<!SORT_)KEY(?![A-Z0-9])|AUTH(?![A-Z0-9])))"
	r"[A-Z0-9_]+\s*(?:=|(?P<colon>:))\s*)"
	r"(?P<value>\"[^\"\n]{6,}\"|'[^'\n]{6,}'|(?(colon)\S[^\n]{5,}|['\"]?[^\s'\"]{6,}['\"]?))",
	re.IGNORECASE,
)

# CLI flags: `--password=X`, `--password X`; a quoted value runs to its closing quote. `-p X` is
# never matched (port, progress).
_CLI_PASSWORD_FLAG = re.compile(
	r"(--?(?:password|passwd|pass|pwd|token|secret|api[-_]?key|bearer)[ =])"
	r"(?P<value>\"[^\"\n]*\"|'[^'\n]*'|[^\s]+)",
	re.IGNORECASE,
)

# `Authorization: Bearer|Basic|Digest|Token <value>`, anywhere in the line.
_HTTP_AUTH_HEADER = re.compile(
	r"(?P<prefix>Authorization\s*:\s*(?:Bearer|Basic|Digest|Token)\s+)(?P<value>[A-Za-z0-9+/=_.\-]{8,})",
	re.IGNORECASE,
)

# `Bearer <token>` outside a header (tracebacks, log lines), any case.
_BEARER_INLINE = re.compile(
	r"(?P<prefix>\bBearer\s+)(?P<value>[A-Za-z0-9+/=_.\-]{16,})\b",
	re.IGNORECASE,
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
