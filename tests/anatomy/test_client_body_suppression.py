"""Anatomy gate — Wing HTTP client classes must not leak upstream
response bodies into exception messages (SEC-10, 2026-05-23).

Pattern: `RuntimeException("HTTP {$code}: " . substr($raw, 0, 500))`
embeds an upstream-server response slice into the caller-visible
exception. Wing catches these in presenters, stores the message into
the /events row (`result.error_message`), which surfaces in /audit
+ launchd.err.log. Authentik 4xx echoes invitation `fixed_data` with
peer-tenant slugs; Infisical 4xx echoes workspace metadata; Stalwart's
notCreated echoes the existing principal's email.

The safe pattern is: throw with just the HTTP status code + a
"check service logs" diagnostic.

This gate sweeps every Model/*Client.php and Model/*Provisioner.php
file, looking for the banned `substr($raw, 0, NNN)` (or equivalent)
inside a `throw new RuntimeException(...)` block.

Currently-passing classes:
- InfisicalClient (SEC-A18 hardening)
- StalwartProvisioner (SEC-A18 hardening)
- AuthentikClient (SEC-10, this change)
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
WING_MODEL = REPO / "files/anatomy/wing/app/Model"


# Files that look like HTTP clients (they curl + throw RuntimeException
# on bad codes). Every PHP file ending in Client.php or Provisioner.php.
def _http_client_files():
	return sorted(
		list(WING_MODEL.glob("*Client.php"))
		+ list(WING_MODEL.glob("*Provisioner.php"))
	)


def test_http_clients_suppress_response_body_in_exceptions():
	"""No `substr((string) $raw, 0, NNN)` inside a throw RuntimeException
	block. The HTTP code is sufficient diagnostics; the raw body lives
	in the upstream service's own logs for forensic recovery."""
	violations = []
	for path in _http_client_files():
		src = path.read_text()
		# Look for any substr extracting from $raw.
		for m in re.finditer(r"substr\(.*?\$raw.*?\)", src):
			# Confirm it's inside a throw block by scanning backwards
			# for the nearest `throw new`.
			pre = src[: m.start()]
			last_throw = pre.rfind("throw new")
			# If a `throw new` exists within 300 chars before the
			# substr, this is a body-leak.
			if last_throw > 0 and (m.start() - last_throw) < 300:
				rel = path.relative_to(REPO)
				violations.append(f"{rel}: substr at offset {m.start()} inside throw")
	assert not violations, (
		"HTTP client classes must not embed upstream response bodies "
		"in exception messages — peer-tenant data leak via /events log. "
		"Found:\n  " + "\n  ".join(violations)
	)


def test_authentik_client_explicitly_suppresses_body():
	"""Belt-and-suspenders: pin the SEC-10 fix in AuthentikClient
	explicitly so any future PR that re-introduces the leak surfaces
	loudly in test names."""
	src = (WING_MODEL / "AuthentikClient.php").read_text()
	# Must NOT have substr($raw...) inside a throw.
	assert "body suppressed" in src, \
		"AuthentikClient should suppress upstream response bodies"
	# Specifically: the HTTP-code throw must not interpolate $raw.
	# Find each `throw new RuntimeException("Authentik`, check the
	# message arg doesn't contain `$raw`.
	for m in re.finditer(
		r'throw new RuntimeException\(\s*"Authentik\s+\{?\$method\}?\s+\{?\$path\}?:\s*HTTP\s+\{?\$code\}?:[^"]*"',
		src,
	):
		msg = m.group(0)
		assert "$raw" not in msg, \
			f"AuthentikClient HTTP-code throw still interpolates $raw: {msg}"
