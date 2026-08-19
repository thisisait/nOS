"""Anatomy gate — Pulse command + args allowlist (SEC-8, 2026-05-23).

Pre-SEC-8, PulsePresenter::actionJobs accepted any `command` value from
any token holder. Combined with TokenRepository having no scope/role
column, every active Wing API token = arbitrary RCE via Pulse on next
tick (Pulse subprocess.run([command, *args]) on the host with operator
UID).

Defense layered:
  1. command MUST be absolute path under an allowed prefix.
  2. basename MUST NOT be a shell interpreter (sh/bash/etc).
  3. basename MUST match a strict alnum + dot/underscore/dash regex.
  4. each arg MUST match a regex banning whitespace + shell metacharacters.

This gate pins all four layers AND verifies that the real plugin
manifests currently in the tree still parse through the validator
(otherwise the operator's working installation would break on next
plugin-loader run).
"""

from __future__ import annotations

import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
PRESENTER = REPO / "files/anatomy/wing/app/Presenters/Api/PulsePresenter.php"
CATALOG = REPO / "files/anatomy/scripts/discover-pulse-catalog.py"


def _allowed_prefixes() -> tuple[str, ...]:
	"""The REAL prefix allowlist, parsed out of the PHP presenter.

	Same reasoning as `_catalog_substitutions` below, and the same mistake made
	twice in one file: `test_real_plugin_manifests_pass_validator` used to
	hand-mirror this list as three literals and omitted `/home/`. Production
	(`PulsePresenter::ALLOWED_COMMAND_PREFIXES` and
	`pulse/runners/subprocess.py::_ALLOWED_PREFIXES`) has carried four since the
	Linux port, and `test_pulse_command_requires_absolute_path` in THIS FILE
	asserts all four — so the file simultaneously required `/home/` of
	production and rejected it on the estate's behalf. It passed on macOS by
	accident of `/Users/` and went red the moment CI ran on a Linux runner,
	whose playbook_dir is `/home/runner/...` (2026-08-02).
	"""
	src = PRESENTER.read_text()
	block = re.search(
		r"ALLOWED_COMMAND_PREFIXES\s*=\s*\[(.*?)\];", src, re.DOTALL
	)
	assert block, (
		"PulsePresenter::ALLOWED_COMMAND_PREFIXES not found — it was renamed or "
		"restructured, and this gate silently stopped covering the real thing"
	)
	prefixes = tuple(re.findall(r"'([^']+)'", block.group(1)))
	assert prefixes, "ALLOWED_COMMAND_PREFIXES parsed as empty"
	return prefixes


def _catalog_substitutions(playbook_dir: str) -> dict[str, str]:
	"""The REAL token→value map, imported from the catalog script.

	Imported rather than mirrored on purpose: a mirrored list is a second
	source of truth that drifts, and when it drifts the test is the thing
	that goes green while production breaks.

	``playbook_dir`` is passed EXPLICITLY (was `setdefault(str(REPO))`,
	2026-08-19): production only ever runs with the checkout under an
	operator home (/Users/… or /home/…), but the forge CI mounts it at /w —
	so deriving the substitution root from where THIS checkout happens to
	sit made the gate test the runner's mount point, not the estate. The
	caller parametrises over both canonical placements instead, which is
	deterministic everywhere and covers both platforms on every run.
	"""
	import importlib.util
	import os

	spec = importlib.util.spec_from_file_location("_pulse_catalog", CATALOG)
	mod = importlib.util.module_from_spec(spec)
	os.environ["NOS_PLAYBOOK_DIR"] = playbook_dir
	try:
		spec.loader.exec_module(mod)
		subs = getattr(mod, "_build_substitutions", None)
		assert callable(subs), (
			f"{CATALOG.name} no longer exposes `_build_substitutions` — the map was "
			"renamed and this gate silently stopped covering the real thing"
		)
		return subs()
	finally:
		del os.environ["NOS_PLAYBOOK_DIR"]


def test_pulse_presenter_has_validate_command():
	"""Method must exist + must be called from actionJobs POST path."""
	src = PRESENTER.read_text()
	assert "private function validatePulseCommand" in src, \
		"validatePulseCommand method missing"
	# Must be called from the POST branch.
	post_idx = src.find("if ($this->getMethod() === 'POST')")
	upsert_idx = src.find("$this->pulse->upsertJob(")
	validate_idx = src.find("$this->validatePulseCommand(")
	assert post_idx < validate_idx < upsert_idx, \
		"validatePulseCommand must run AFTER req-field checks and BEFORE upsertJob"


def test_pulse_command_requires_absolute_path():
	src = PRESENTER.read_text()
	# The string literal of the error message is the canonical anchor.
	assert "command must be an absolute path" in src
	# Must also check the prefix allowlist.
	assert "ALLOWED_COMMAND_PREFIXES" in src
	# Must contain the canonical safe prefixes — incl. host-home on BOTH
	# platforms (/Users on macOS, /home on Linux; playbook_dir-rooted scripts).
	for prefix in ("/opt/homebrew/bin/", "/usr/local/bin/", "/Users/", "/home/"):
		assert f"'{prefix}'" in src, f"ALLOWED_COMMAND_PREFIXES must include {prefix}"

	# Python runner must stay in lockstep with the PHP presenter.
	runner = (REPO / "files/anatomy/pulse/pulse/runners/subprocess.py").read_text()
	for prefix in ("/Users/", "/home/"):
		assert f'"{prefix}"' in runner, f"subprocess._ALLOWED_PREFIXES must include {prefix}"


def test_pulse_basename_banned_for_shell_interpreters():
	src = PRESENTER.read_text()
	assert "BANNED_BASENAMES" in src
	for banned in ("sh", "bash", "zsh", "sudo", "su"):
		assert f"'{banned}'" in src, f"BANNED_BASENAMES must include '{banned}'"


def test_pulse_arg_regex_bans_whitespace_and_shell_meta():
	"""The arg regex must reject anything that could shell-inject if a
	future code path drops the argv array form. Whitespace + shell-meta
	+ quotes specifically banned."""
	src = PRESENTER.read_text()
	# Extract ARG_REGEX literal.
	m = re.search(r"ARG_REGEX\s*=\s*'(/[^']+/)';", src)
	assert m, "ARG_REGEX constant not found"
	regex_pattern = m.group(1)
	# Compile + verify behaviour with sample strings.
	# Strip leading/trailing `/` and PHP-style modifiers.
	import re as _re
	core = regex_pattern.strip('/')
	pat = _re.compile(core)

	# Should PASS — real-world args.
	for ok in (
		"/Users/pazny/wing/app/bin/dispatch-notifications.php",
		"--key=value",
		"http://127.0.0.1:9000/api/v1/events",
		"foo.bar_baz",
		"",
	):
		assert pat.fullmatch(ok), f"arg regex must accept '{ok}'"

	# Should FAIL — injection-shaped.
	for bad in (
		"rm -rf /",          # whitespace
		"`id`",              # backtick
		"$(whoami)",         # command substitution
		"foo; bar",          # ;
		"foo | bar",         # pipe
		"foo > /tmp/x",      # redirect
		"foo & echo",        # background + amp
		"foo\nbar",          # newline
		"foo'bar",           # quote
		'foo"bar',           # double quote
	):
		assert not pat.fullmatch(bad), f"arg regex must reject '{bad}'"


def test_pulse_tokens_are_bare_not_filtered():
	"""discover-pulse-catalog.py substitutes pulse command/env tokens by LITERAL
	string-replace keyed on bare "{{ name }}". A filter form ("{{ name | default(x) }}")
	never matches → the literal unrendered string ships into pulse_jobs and the job
	fails at runtime (e.g. an HMAC secret that's the string "{{ bone_secret … }}").
	Caught live by the conductor 2026-05-25 (gitleaks WING_EVENTS_HMAC_SECRET).
	Guard: no Jinja token in a pulse job command/env may contain a `|` filter."""
	import yaml

	# The wing-base dispatch iceberg (conditional Jinja → unrendered mail/ntfy
	# env) was FIXED 2026-05-26: wing post.yml Ansible-renders the values into
	# NOS_* env, wing-base carries bare tokens, the catalog table maps them.
	# No quarantine remains — every pulse token must now be bare.
	KNOWN_UNRENDERED: set = set()

	filtered = re.compile(r"\{\{[^}]*\|[^}]*\}\}")
	manifests = list((REPO / "files/anatomy/plugins").rglob("plugin.yml")) \
		+ list((REPO / "files/anatomy/agents").glob("*.yml"))
	offenders = []
	for path in manifests:
		plugin = path.parent.name if path.parent.name != "agents" else path.stem
		try:
			doc = yaml.safe_load(path.read_text()) or {}
		except yaml.YAMLError:
			continue
		for job in ((doc.get("pulse") or {}).get("jobs") or []):
			if (plugin, job.get("name")) in KNOWN_UNRENDERED:
				continue
			# Check EVERY field the catalog literal-substitutes: command, schedule,
			# args, env values. (schedule/args were a blind spot — the digest
			# job's schedule shipped a filter token literal, 2026-05-26.)
			vals = [str(job.get("command", "")), str(job.get("schedule", ""))] \
				+ [str(a) for a in (job.get("args") or [])] \
				+ [str(v) for v in (job.get("env") or {}).values()]
			for v in vals:
				if filtered.search(v):
					offenders.append(f"{path.relative_to(REPO)} [{job.get('name')}]: {v}")
	assert not offenders, (
		"pulse command/env tokens must be bare (catalog does literal replace, "
		f"no Jinja filters): {offenders}"
	)


@pytest.mark.parametrize("playbook_dir", [
	"/Users/operator/projects/nOS",   # macOS estate placement
	"/home/operator/projects/nOS",    # Linux estate placement
])
def test_real_plugin_manifests_pass_validator(playbook_dir):
	"""Critical: the validator must accept commands that LIVE plugin
	manifests already register. Otherwise the next plugin-loader run
	breaks operator's working install.

	Parametrised over BOTH canonical checkout roots (2026-08-19): a
	{{ playbook_dir }}-rooted command only passes the validator because the
	estate keeps the checkout under an operator home — asserting that for
	/Users AND /home on every run is strictly stronger than asserting it
	for wherever this particular checkout is mounted (the forge CI mounts
	at /w, which is not, and must never be treated as, a supported estate
	placement)."""
	subs = _catalog_substitutions(playbook_dir)
	plugin_files = list((REPO / "files/anatomy/plugins").rglob("plugin.yml"))
	# Find every `command:` value under a `jobs:` block.
	for path in plugin_files:
		src = path.read_text()
		# Look for `jobs:` followed by `- name:` and `command:`.
		if "jobs:" not in src:
			continue
		# Iterate over each command line.
		for m in re.finditer(r"command:\s*[\"']?([^\"'\n]+)[\"']?", src):
			cmd = m.group(1).strip()
			# Substitute the way PRODUCTION does — from the catalog's own map
			# (see test_catalog_renders_every_token, which pins the same thing
			# end-to-end).
			#
			# This used to be a hand-kept list of .replace() calls, and on
			# 2026-08-01 that cost a failed converge: backup-base shipped
			# `{{ backup_verify_command }}` — a var defined NOWHERE — and the
			# fix applied here was to teach THIS TEST to render it. The gate
			# went green by being told an answer production did not have; the
			# catalog passed the literal braces through and Wing 400'd the
			# upsert. A gate you can satisfy by editing the gate is not one.
			cmd_rendered = cmd
			for token, value in subs.items():
				cmd_rendered = cmd_rendered.replace(token, value or "/Users/pazny/x")
			# Prefix check, PARSED from the PHP rather than mirrored — see
			# _allowed_prefixes() for what mirroring it cost.
			allowed = cmd_rendered.startswith(_allowed_prefixes())
			assert allowed, (
				f"Live plugin manifest {path.relative_to(REPO)} declares "
				f"command={cmd_rendered!r} which would be REJECTED by "
				f"PulsePresenter::validatePulseCommand. Either tighten "
				f"the manifest OR extend ALLOWED_COMMAND_PREFIXES."
			)
			basename = cmd_rendered.rsplit("/", 1)[-1]
			banned = ("sh", "bash", "zsh", "dash", "csh", "ksh",
			          "fish", "sudo", "su", "env")
			assert basename not in banned, (
				f"Live plugin manifest {path.relative_to(REPO)} declares "
				f"banned basename '{basename}' (shell interpreter)"
			)
