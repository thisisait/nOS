"""Anatomy gate: no `curl_close()` calls in Wing PHP code (2026-05-18).

PHP 8.5 deprecated `curl_close()` — it's a no-op since 8.0 (cURL handles
became objects with __destruct, not resources). FrankenPHP's default
error reporting surfaces E_DEPRECATED as HTTP 500, so a single forgotten
`curl_close($ch)` takes down the whole presenter.

Two prior incidents:
  * 2026-05-17 (pre-this-gate): 9 files cleaned up in the initial sweep.
  * 2026-05-18: AuthentikClient.php + dispatch-notifications.php slipped
    through, broke /users immediately on the first live run.

This gate forbids any new `curl_close(` call in the Wing PHP tree.
Comments that *mention* curl_close (explaining why it's removed) are
fine — only actual call sites match.
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
WING_PHP_ROOTS = [
	REPO / "files/anatomy/wing/app",
	REPO / "files/anatomy/wing/bin",
]


def test_no_curl_close_calls_in_wing_php():
	offenders: list[tuple[str, int, str]] = []
	# Match `curl_close(` only at the start of a statement — not in
	# strings, not in comments. A real call line is one where curl_close
	# appears OUTSIDE a `//` or `*` comment.
	for root in WING_PHP_ROOTS:
		if not root.is_dir():
			continue
		for php in root.rglob("*.php"):
			# Skip vendor/ — third-party code lives at its own cadence.
			if "/vendor/" in str(php):
				continue
			for line_no, line in enumerate(php.read_text().splitlines(), 1):
				# Detect a real call: `curl_close(` not preceded by `// ` or `* `
				if "curl_close(" not in line:
					continue
				# Strip leading whitespace to look at comment markers.
				stripped = line.lstrip()
				if stripped.startswith("//") or stripped.startswith("*") or stripped.startswith("#"):
					continue
				# `* curl_close(` in a docblock continuation
				if re.match(r"^\s*\*", line):
					continue
				offenders.append((
					str(php.relative_to(REPO)),
					line_no,
					line.strip(),
				))
	assert not offenders, (
		"curl_close() calls remain in Wing PHP (PHP 8.5 deprecated → "
		f"FrankenPHP 500). Remove and replace with `unset($ch);` or let "
		f"$ch fall out of scope:\n"
		+ "\n".join(f"  {f}:{ln}  {code}" for f, ln, code in offenders)
	)
