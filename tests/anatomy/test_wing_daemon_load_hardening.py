"""Anatomy gate for Wing daemon load idempotence (A17, 2026-05-20).

Pre-A17 the bootstrap task in pazny.wing/tasks/main.yml AND the
"Restart wing" handler in main.yml both swallowed errors via
`failed_when: false`. A plist syntax error / port conflict /
missing FrankenPHP binary would leave the daemon down with NO
diagnostic — surfaced live 2026-05-18 when wing.pazny.eu was 502
despite the playbook reporting green.

Fix: both code paths now probe `http://127.0.0.1:<wing_port>/` up to
20 times before giving up; if no response within ~10s, they dump
`launchctl print` state + `launchd.err.log` tail and EXIT NON-ZERO.
The playbook fails fast with a useful diagnostic instead of silently
leaving the operator with a broken Wing.

This gate pins both code paths against regression of the
`failed_when: false` anti-pattern.
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]


def test_wing_role_bootstrap_carries_health_probe():
	src = (REPO / "roles/pazny.wing/tasks/main.yml").read_text()
	# Must contain a uri-based probe with retries.
	assert "Wait for daemon to bind" in src
	assert "ansible.builtin.uri" in src
	# Retry contract — at least 10 retries with at most 2s delay.
	probe_block_start = src.find("Wait for daemon to bind")
	probe_block_end = src.find("\n- name:", probe_block_start + 1)
	probe = src[probe_block_start:probe_block_end]
	m = re.search(r"retries:\s*(\d+)", probe)
	assert m and int(m.group(1)) >= 10, "probe must retry ≥ 10 times"


def test_wing_role_fails_loud_on_dead_daemon():
	src = (REPO / "roles/pazny.wing/tasks/main.yml").read_text()
	# A fail task must follow the probe.
	assert "Fail-loud if daemon never came up" in src
	assert "ansible.builtin.fail" in src
	# The diagnose task captures launchctl + log tail.
	assert "Diagnose dead daemon" in src
	assert "launchctl print" in src


def test_main_yml_restart_wing_handler_probes_after_bootstrap():
	src = (REPO / "main.yml").read_text()
	# Find the "Restart wing" handler block.
	start = src.find("- name: Restart wing")
	assert start > 0
	# Next "- name:" delimits the handler.
	end = src.find("\n    - name:", start + 10)
	handler = src[start:end]
	# Health probe inside the inline shell.
	assert "curl -sS" in handler
	assert "code=$(curl" in handler or "code=$( curl" in handler or 'code=$(curl' in handler
	assert "for i in $(seq 1 20)" in handler
	# Fail-loud branch — explicit exit 1 on probe exhaustion.
	assert "exit 1" in handler
	# Diagnostic dump on failure.
	assert "launchctl print" in handler
	assert "launchd.err.log" in handler


def test_main_yml_restart_wing_handler_dropped_silent_failure_flag():
	"""Pre-A17 the handler had `failed_when: false` which hid every
	failure mode. The handler MUST NOT carry that anymore — only
	`changed_when: true` is acceptable."""
	src = (REPO / "main.yml").read_text()
	start = src.find("- name: Restart wing")
	end = src.find("\n    - name:", start + 10)
	handler = src[start:end]
	# `failed_when: false` (whitespace-tolerant) MUST NOT be present
	# at top level of the handler. Comments mentioning it ARE allowed
	# (they explain WHY it was dropped).
	for line in handler.splitlines():
		stripped = line.strip()
		if stripped.startswith("#"):
			continue
		assert not re.match(r"^failed_when\s*:\s*false\s*$", stripped), (
			"Restart wing handler still has `failed_when: false` — A17 "
			"surfaces dead daemons via non-zero exit; this flag would "
			"hide that signal"
		)
