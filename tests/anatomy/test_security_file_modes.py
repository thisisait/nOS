"""Anatomy gate — security-sensitive file modes (SEC-11+SEC-1+SEC-4, 2026-05-23).

The systematic security audit found multiple cases where private keys,
secrets files, and credential-bearing artifacts were written with mode
0644 (world-readable by other local UIDs). The root cause is the same
across every case: the `mode:` value drifts from defense-in-depth
default (0600/0700) toward the convenient default (0644).

This gate enumerates every `ansible.builtin.{copy,template,file}` task
in the playbook whose `dest:` looks like a key, credential, or persisted
secret, and asserts the mode is 0600 (file) or 0700 (directory).

Pinned to prevent regression of:
- SEC-11: ACME wildcard private key (was 0644)
- SEC-1:  Plugin loader rendered overrides (was 0644)
- SEC-4:  ~/.nos/ directory (drifts to 0755 vs 0700)
- A18:    Wing/Bone/Pulse launchd plists (must stay 0600)
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]


# File-name patterns that indicate sensitive content. Match against `dest:`
# values in Ansible task YAML.
SECRET_DEST_PATTERNS = [
	r"\.key($|[\"'])",                           # private keys
	r"\.pem($|[\"'])",                           # PEM-bundled keys/certs
	r"\.nos/secrets\.yml",                       # operator runtime secrets
	r"LaunchAgents/eu\.thisisait\.nos\..*\.plist",  # anatomy daemon plists
	r"credentials\.yml",                         # operator credentials override
]

# .crt, .cer fullchain files, and the mkcert rootCA.pem are PUBLIC
# trust anchors — they contain no private material and need to be
# world-readable so containers can mount them as the OS trust store.
# The PRIVATE key counterparts (rootCA-key.pem, *.eu.key) live elsewhere
# and ARE caught by the SECRET_DEST_PATTERNS above.
PUBLIC_CERT_PATTERNS = [
	r"fullchain\.cer",
	r"\.crt",
	r"rootCA\.pem$",        # mkcert public CA cert (not -key.pem)
]


def _enumerate_tasks():
	"""Walk every YAML file in roles/ + tasks/ + main.yml, find each
	`ansible.builtin.{copy,template,file}` task block, return tuples of
	(filepath, lineno, dest_value, mode_value)."""
	roots = [REPO / "main.yml"]
	roots += list((REPO / "tasks").rglob("*.yml"))
	roots += list((REPO / "roles").rglob("tasks/*.yml"))
	roots += list((REPO / "roles").rglob("tasks/**/*.yml"))

	# Per task: src + dest + mode keys live in a contiguous block. We
	# slurp the file, then split on lines beginning with `- name:` at
	# any indent. For each chunk, look for the module name + dest + mode.
	task_re = re.compile(
		r"ansible\.builtin\.(copy|template|file)\b",
	)
	dest_re = re.compile(r"^\s*dest:\s*[\"']?([^\"'\n]+)[\"']?", re.MULTILINE)
	mode_re = re.compile(r"^\s*mode:\s*[\"']?([\d]{3,4})[\"']?", re.MULTILINE)

	for path in roots:
		if not path.is_file():
			continue
		text = path.read_text()
		# Split into rough task blocks on `- name:`.
		for block in re.split(r"\n(?=\s*- name:)", text):
			if not task_re.search(block):
				continue
			d = dest_re.search(block)
			m = mode_re.search(block)
			if d and m:
				yield (path, d.group(1).strip(), m.group(1).strip())


def test_secret_files_have_0600_mode():
	"""Every task whose `dest:` matches a secret-like pattern must set
	`mode:` to 0600 (or 0400 if read-only). Reject 0644, 0640, 0755."""
	bad = []
	for path, dest, mode in _enumerate_tasks():
		# Skip public-cert exceptions (fullchain, .crt).
		if any(re.search(p, dest) for p in PUBLIC_CERT_PATTERNS):
			continue
		if not any(re.search(p, dest) for p in SECRET_DEST_PATTERNS):
			continue
		# Normalize mode (strip leading 0 if 4 chars).
		m = mode.lstrip("0") or "0"
		# Accept 600 / 400.
		if m in ("600", "400"):
			continue
		rel = path.relative_to(REPO)
		bad.append(f"{rel}: dest={dest} mode={mode} (expected 0600 or 0400)")
	assert not bad, (
		"Secret-like files MUST be mode 0600 (or 0400). Found:\n  "
		+ "\n  ".join(bad)
	)


def test_nos_dir_created_at_0700_in_pre_tasks():
	"""SEC-4 (2026-05-23): ~/.nos contains persisted secrets (admin
	tokens, KMS encryption keys, APP_KEYs, JWT secrets, Bluesky PDS
	rotation key). The directory must be 0700 — any wider mode lets a
	local UID enumerate which secret-files exist via `ls ~/.nos`.

	Pre-SEC-4, tasks/stacks/core-up.yml created it as part of a 0755
	loop; state_manager later tightened to 0700; whichever ran last
	won. Now: created in main.yml::pre_tasks at 0700 unconditionally,
	BEFORE any other task touches it. The 0755 entry in core-up.yml
	was removed."""
	src = (REPO / "main.yml").read_text()
	# Pre-task: 0700 creation must exist BEFORE the persisted-secrets
	# stat task (or any role).
	pre_task_idx = src.find('"[Secrets] Ensure ~/.nos directory exists at 0700"')
	assert pre_task_idx > 0, "Pre-task ensuring ~/.nos at 0700 not present in main.yml"
	stat_idx = src.find('"[Secrets] Check for persisted secrets file"')
	assert stat_idx > pre_task_idx, \
		"~/.nos 0700 task must come BEFORE the secrets-file stat (else stat may run on missing dir)"

	# core-up.yml MUST NOT recreate ~/.nos at 0755.
	coreup = (REPO / "tasks/stacks/core-up.yml").read_text()
	assert "/.nos\", enabled:" not in coreup, \
		"core-up.yml must not recreate ~/.nos — it's owned by main.yml pre_tasks at 0700"


def test_acme_key_explicitly_pinned_to_0600():
	"""Belt-and-suspenders: the ACME wildcard private key task is the
	highest-impact case (gates every *.tenant_domain route). Pin
	explicitly so a future PR can't regress past the sweep."""
	src = (REPO / "roles/pazny.acme/tasks/main.yml").read_text()
	# Find the {zone}.key install task.
	idx = src.find("Install {zone}.key")
	assert idx > 0, "ACME key install task not found"
	# Look for mode in the next ~400 chars.
	block = src[idx:idx + 600]
	assert "mode: '0600'" in block or 'mode: "0600"' in block, \
		"ACME key install task must set mode: '0600'"
