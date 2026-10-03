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


def _catalog_substitutions(playbook_dir: str, extra: dict[str, str] | None = None) -> dict[str, str]:
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
	env = {"NOS_PLAYBOOK_DIR": playbook_dir, **(extra or {})}
	os.environ.update(env)
	try:
		spec.loader.exec_module(mod)
		subs = getattr(mod, "_build_substitutions", None)
		assert callable(subs), (
			f"{CATALOG.name} no longer exposes `_build_substitutions` — the map was "
			"renamed and this gate silently stopped covering the real thing"
		)
		return subs()
	finally:
		for k in env:
			del os.environ[k]


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
	# Since 2026-10-03 a whole home is NOT a prefix (workload-allowlist):
	# ~/Downloads/x.py passed both sides until then.
	for prefix in ("/Users/", "/home/"):
		assert f"'{prefix}'" not in src, f"ALLOWED_COMMAND_PREFIXES must not include {prefix}"


def _php_list(name: str) -> tuple[str, ...]:
	m = re.search(rf"const {name}\s*=\s*\[(.*?)\];", PRESENTER.read_text(), re.DOTALL)
	assert m, f"PulsePresenter::{name} not found"
	return tuple(re.findall(r"'([^']+)'", m.group(1)))


def test_runner_and_presenter_declare_the_same_trees():
	"""Lockstep, parsed from both artifacts: the PHP gate at registration and the
	Python gate at exec must allow exactly the same thing."""
	run = _runner()
	assert _php_list("ALLOWED_COMMAND_PREFIXES") == run._SYSTEM_PREFIXES
	assert _php_list("REPO_TREES") == run._REPO_TREES
	assert _php_list("HOME_TREES") == run._HOME_TREES
	m = re.search(r"INTERPRETER_REGEX = '/(.+?)/';", PRESENTER.read_text())
	assert m and m.group(1) == run._INTERPRETER_RE.pattern


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
		+ list((REPO / "files/anatomy/agents").glob("*/agent.yml"))
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
def test_real_plugin_manifests_pass_validator(playbook_dir, monkeypatch):
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
	import yaml
	home = playbook_dir.rsplit("/projects/", 1)[0]
	subs = _catalog_substitutions(playbook_dir, {
		"NOS_HOME": home, "NOS_WING_HOME": f"{home}/wing", "NOS_WING_APP_DIR": f"{home}/wing/app",
		"NOS_BACKUP_VERIFY_SCRIPT": f"{home}/.nos/backup-verify.sh"})
	run = _runner()
	monkeypatch.setenv("HOME", home)
	monkeypatch.setenv("NOS_REPO_ROOT", playbook_dir)
	plugin_files = list((REPO / "files/anatomy/plugins").rglob("plugin.yml"))
	# Find every `command:` value under a `jobs:` block.
	for path in plugin_files:
		src = path.read_text()
		# Look for `jobs:` followed by `- name:` and `command:`.
		if "jobs:" not in src:
			continue
		jobs = ((yaml.safe_load(src) or {}).get("pulse") or {}).get("jobs") or []
		job_args = {str(j.get("command", "")).strip(): j.get("args") or [] for j in jobs}
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
			args = [str(a) for a in job_args.get(cmd, [])]
			for token, value in subs.items():
				args = [a.replace(token, value or "/Users/pazny/x") for a in args]
			try:
				run.validate_command(cmd_rendered, args)
			except run.CommandRejected as exc:
				pytest.fail(
					f"Live plugin manifest {path.relative_to(REPO)} declares "
					f"command={cmd_rendered!r} args={args!r}, REJECTED by the "
					f"runner ({exc}). Move the script into a Pulse tree or extend "
					f"REPO_TREES/HOME_TREES on BOTH sides."
				)


def _runner():
	import importlib.util
	import sys
	spec = importlib.util.spec_from_file_location(
		"_pulse_subprocess", REPO / "files/anatomy/pulse/pulse/runners/subprocess.py")
	mod = importlib.util.module_from_spec(spec)
	sys.modules[spec.name] = mod  # dataclasses resolve their module by name
	try:
		spec.loader.exec_module(mod)
	finally:
		sys.modules.pop(spec.name, None)
	return mod


def test_the_daemons_own_home_is_allowed_on_both_sides(monkeypatch):
	"""`/root` (a container, a server install) is an operator home too.
	MEASURED 2026-09-25: the cloud sandbox runs as root and every host-script
	job 400'd at registration. Both sides root HOME_TREES at $HOME — and
	HOME=/ or empty roots nothing."""
	src = PRESENTER.read_text()
	assert "$this->allowedCommandPrefixes()" in src
	assert "self::root('HOME')" in src and "self::root('NOS_REPO_ROOT')" in src
	run = _runner()
	monkeypatch.setenv("HOME", "/root")
	run.validate_command("/root/.local/bin/frankenphp", ["php-cli", "/root/wing/app/bin/x.php"])
	for bad in ("/", ""):
		monkeypatch.setenv("HOME", bad)
		with pytest.raises(run.CommandRejected):
			run.validate_command("/etc/evil", [])


REPO_ROOT = "/Users/op/projects/nOS"


@pytest.mark.parametrize("command,args", [
	("/Users/op/Downloads/x.py", []),                                    # a planted script
	("/Users/op/projects/nOS/tools/../../../Downloads/x.py", []),         # traversal out of a tree
	("/Users/op/projects/other/tools/x.py", []),                         # a different checkout
	("/opt/homebrew/bin/python3", ["/Users/op/Downloads/x.py"]),         # interpreter, planted script
	("/opt/homebrew/bin/python3", ["-m", "pip", "install", "evil"]),     # interpreter, no script
	("/opt/homebrew/bin/php", ["/Users/op/wing/../Downloads/x.php"]),     # traversal in the script
	("/Users/op/.local/bin/frankenphp", ["php-cli", "/tmp/x.php"]),
])
def test_a_command_outside_the_trees_is_refused(command, args, monkeypatch):
	run = _runner()
	monkeypatch.setenv("HOME", "/Users/op")
	monkeypatch.setenv("NOS_REPO_ROOT", REPO_ROOT)
	with pytest.raises(run.CommandRejected):
		run.validate_command(command, args)


@pytest.mark.parametrize("command,args", [
	(f"{REPO_ROOT}/tools/red-status.py", []),
	(f"{REPO_ROOT}/files/anatomy/plugins/gitleaks/skills/scan.sh", []),
	("/opt/homebrew/bin/php", ["/Users/op/wing/app/bin/breach-scan.php"]),
	("/Users/op/.nos/backup-verify.sh", []),
	("/opt/homebrew/bin/gitleaks", ["detect", "--no-git"]),
])
def test_a_declared_command_runs(command, args, monkeypatch):
	run = _runner()
	monkeypatch.setenv("HOME", "/Users/op")
	monkeypatch.setenv("NOS_REPO_ROOT", REPO_ROOT)
	run.validate_command(command, args)


def test_repo_trees_need_the_daemons_to_know_the_checkout():
	"""NOS_REPO_ROOT unset = no repo tree = every repo job refused. Both daemons get it."""
	assert "<key>NOS_REPO_ROOT</key>" in (REPO / "roles/pazny.pulse/templates/pulse.plist.j2").read_text()
	assert "NOS_REPO_ROOT:" in (REPO / "roles/pazny.pulse/tasks/main.yml").read_text()
	assert "<key>NOS_REPO_ROOT</key>" in (REPO / "roles/pazny.wing/templates/wing.plist.j2").read_text()
	assert "\nNOS_REPO_ROOT=" in (REPO / "roles/pazny.wing/templates/wing.env.j2").read_text()


def test_linux_php_jobs_are_repointed_at_frankenphp():
	"""/opt/homebrew/bin/php does not exist on Linux: every Wing PHP job would
	exit 127 per tick. The catalog rewrites argv0 from NOS_PHP_ARGV."""
	import importlib.util
	import os
	spec = importlib.util.spec_from_file_location("_pulse_catalog2", CATALOG)
	mod = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(mod)
	job = {"command": "/opt/homebrew/bin/php", "args": ["/h/wing/app/bin/a.php"]}
	os.environ["NOS_PHP_ARGV"] = "/home/u/.local/bin/frankenphp php-cli"
	try:
		out = mod._platform_php(job)
		assert out["command"] == "/home/u/.local/bin/frankenphp"
		assert out["args"] == ["php-cli", "/home/u/wing/app/bin/a.php".replace("/home/u/", "/h/")]
		os.environ["NOS_PHP_ARGV"] = ""
		assert mod._platform_php(job) == job, "macOS: left as authored"
	finally:
		os.environ.pop("NOS_PHP_ARGV", None)
	post = (REPO / "roles/pazny.wing/tasks/post.yml").read_text()
	assert "NOS_PHP_ARGV:" in post
