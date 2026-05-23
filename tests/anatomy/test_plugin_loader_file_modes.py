"""Anatomy gate — plugin loader writes overrides with mode 0600 (SEC-1, 2026-05-23).

Surfaced by the systematic security audit. Rendered compose-extension
overrides routinely contain plaintext OIDC client_secrets, DB passwords,
SMTP creds, JWT secrets — anything a plugin's `compose_extension` block
projects into env vars. `Path.write_text()` inherits the process umask
(typically 022 → file mode 0644), which exposed every override under
~/stacks/*/overrides/ to any local UID on the macOS host.

These gates pin:
  * _render_file uses the open-with-mode pattern (NOT bare write_text)
  * 0600 (file) + 0700 (parent dir) modes are explicit in the source
  * Atomic write via tmp+os.replace so partial renders don't leak
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
LOADER = REPO / "files/anatomy/module_utils/load_plugins.py"


def test_render_file_uses_open_with_mode_pattern():
	"""The render path must explicitly create files with mode 0600 via
	os.open + O_WRONLY|O_CREAT|O_TRUNC. Path.write_text alone is BANNED
	in _render_file's body because it has no mode= kwarg in Py3.9 and
	silently inherits umask."""
	src = LOADER.read_text()
	# Extract _render_file body.
	m = re.search(r"def _render_file\(.*?\)(.*?)(?=\ndef )", src, re.DOTALL)
	assert m, "_render_file not found in load_plugins.py"
	body = m.group(1)
	# Must use os.open with explicit mode.
	assert "os.open(" in body, "_render_file must use os.open (not Path.write_text)"
	assert "0o600" in body, "_render_file must set mode 0o600 explicitly"
	# Must NOT call bare write_text on the dest (write_text has no
	# mode= kwarg; would inherit umask 0644).
	assert "dest.write_text" not in body, (
		"_render_file must NOT use dest.write_text — it inherits "
		"the process umask 0022 → file mode 0644 (plaintext secret leak)"
	)


def test_render_file_atomic_via_tmp_and_replace():
	"""Partial renders must not leave a half-written override on disk —
	docker compose up would parse the partial YAML and crash or, worse,
	skip the secret env block silently. Atomic-ish: write to .tmp +
	os.replace = atomic rename on POSIX."""
	src = LOADER.read_text()
	m = re.search(r"def _render_file\(.*?\)(.*?)(?=\ndef )", src, re.DOTALL)
	body = m.group(1)
	assert "os.replace(" in body, "_render_file must use os.replace for atomic rename"
	# Must reference a .tmp suffix or tmp variable.
	assert ".tmp" in body or "tempfile" in body, \
		"_render_file must write through a tmp path before replacing dest"


def test_render_file_locks_parent_dir_to_0700():
	"""The ~/stacks/<stack>/overrides/ directory holds every plugin
	override. Even though each FILE is 0600, a 0755 parent dir lets
	other UIDs `ls` the directory and learn which services are deployed
	— enumeration that helps a local attacker pick targets. Lock parent
	to 0700 too."""
	src = LOADER.read_text()
	m = re.search(r"def _render_file\(.*?\)(.*?)(?=\ndef )", src, re.DOTALL)
	body = m.group(1)
	assert "0o700" in body, \
		"_render_file must chmod parent dir to 0o700 (defense vs UID enumeration)"


def test_loader_has_no_bare_write_text_in_render_paths():
	"""Sweep: any future render-like helper that uses Path.write_text
	on a file that COULD carry secrets must be flagged. The full module
	source must not introduce a regression to write_text in any function
	whose name suggests rendering (render, write, dump, emit, persist).
	`with_suffix(...).write_text` patterns in non-render utilities are
	allowed (Sphinx-style doc generators, smoke harness, etc.)."""
	src = LOADER.read_text()
	# Find every function definition and check its body for write_text
	# IF the function name is render-shaped.
	for m in re.finditer(r"def (\w+)\(.*?\)(.*?)(?=\ndef |\Z)", src, re.DOTALL):
		name, body = m.group(1), m.group(2)
		if any(kw in name.lower() for kw in ("render", "emit", "persist")):
			assert "write_text(" not in body, (
				f"_render path `{name}` uses write_text which inherits umask. "
				f"Use the os.open+os.replace pattern in _render_file."
			)
