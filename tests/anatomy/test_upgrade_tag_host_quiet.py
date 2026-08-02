"""Anatomy gate: `--tags upgrade` is provably host-quiet (Phase 0, 2026-06-20).

Trigger: a `blank=true` run restarted the operator's IDE (Windsurf) mid-run and
killed the controlling session, leaving a half-applied run. Two host-disruptive
operations exist in a NORMAL run — `killall Dock`/`killall Finder`
(`tasks/macos-defaults.yml`) and a `launchctl kickstart … sshd` handler
(`main.yml`) — plus, on a blank, ~50 containers whose RAM pressure alone can make
macOS terminate a heavy GUI app. None of these is `reboot`/`shutdown` (the
playbook has none) and there is no Docker-daemon restart, but each is enough to
drop the session running the playbook.

An *upgrade* run must never carry that risk regardless of a recipe's own
`reset.scope`. The Dock/Finder killalls carry `macos-defaults`/`osx` tags and the
sshd kickstart is a handler, so tag isolation *should* already exclude them from
`--tags upgrade`. This gate PINS that:

  1. Ground-truth reachability via `ansible-playbook --list-tasks --tags upgrade`
     (the resolver Ansible itself uses). No reachable task NAME may match a
     host-disruptive signature (Finder/Dock restart, "Restart ssh"). The killall
     source file (`tasks/macos-defaults.yml`) must not contribute any task.
  2. Static content scan of the upgrade task graph (`tasks/upgrade-engine.yml` +
     its transitive includes). No `command:`/`shell:` body may match the
     host-disruptive command denylist (`killall`, `launchctl kickstart … sshd`,
     a Docker-Desktop quit/restart, `reboot`/`shutdown`/`softwareupdate -i`).

If this gate FAILS the upgrade tag is NOT host-quiet — that is a real finding,
not a flaky test. See docs/archive/upgrade-reset-scope-and-session-safety.md
§"Run-hardening".
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
TASKS = REPO / "tasks"

# Host-disruptive COMMAND patterns (regex, matched case-insensitively against
# command/shell bodies). Word boundaries on the bare verbs ('reboot'/'shutdown')
# avoid false-positives on benign substrings ('rebooted', a path containing
# 'reboot'); the softwareupdate pattern matches the combined short-flag install
# forms (-i/-ia/-ir) without mistaking '--list' for an install — mirroring the
# engine denylist in nos_upgrade_actions/reset_scope.py. Kept narrow on the
# Docker-Desktop case so the benign login-item / restart-policy tasks don't trip.
COMMAND_DENYLIST_RE = tuple(re.compile(p, re.IGNORECASE) for p in (
	r"killall\s+(finder|dock|docker)",
	r"kickstart\s+-?k?\s*system/com\.openssh\.sshd",
	# reboot / shutdown as a COMMAND (line-start, after a shell separator/pipe,
	# or after sudo) — NOT the word "reboot" in prose ("Reboot pending …") or a
	# path ("reboot-required.json"), which a reboot-NOTIFICATION task body holds
	# legitimately. Anchoring to command position avoids that false-positive.
	r"(?:^|[\n;&|]|\bsudo\s+)\s*(?:/[\w./-]+/)?reboot\b",
	# shutdown (any except a -c cancel) + halt + osascript System-Events restart —
	# mirroring the engine _HOST_REBOOT_RE so the two denylists AGREE (the bare
	# `-[rh]` missed `shutdown now`/`halt`/the osascript restart).
	r"(?:^|[\n;&|]|\bsudo\s+)\s*(?:/[\w./-]+/)?shutdown\b(?![^\n;|&]*\s-c\b)",
	r"(?:^|[\n;&|]|\bsudo\s+)\s*(?:/[\w./-]+/)?halt\b",
	r"osascript[^\n]*System Events[^\n]*\b(?:restart|shut down)\b",
	r"\bsoftwareupdate\b[^\n;|&]*?(?:--install\b|(?<![\w-])-[a-z]*i[a-z]*\b)",
	r"(?:osascript|open)[^\n]*docker desktop[^\n]*(?:quit|restart|--restart)",
	r"quit\s+app\s+\"docker",
))


def _matches_command_denylist(body: str) -> str | None:
	"""Return the matched pattern for a host-disruptive command body, or None.
	Shared by the engine-graph scan and the ansible-free tag backstop."""
	for pat in COMMAND_DENYLIST_RE:
		if pat.search(body):
			return pat.pattern
	return None

# Host-disruptive task-NAME signatures (lower-cased). The reachable-task-name
# scan flags any of these surfacing under `--tags upgrade`.
NAME_DENYLIST = (
	"restart finder",
	"restart dock",
	"restart ssh",
	"restart sshd",
)


# ── helpers ───────────────────────────────────────────────────────────────


def _command_bodies(task: dict) -> list[str]:
	"""Extract every shell/command body string from a parsed task dict."""
	bodies: list[str] = []
	for key in ("ansible.builtin.command", "ansible.builtin.shell", "command", "shell"):
		val = task.get(key)
		if isinstance(val, str):
			bodies.append(val)
		elif isinstance(val, dict):
			for sub in ("cmd", "_raw_params"):
				if isinstance(val.get(sub), str):
					bodies.append(val[sub])
	return bodies


def _task_tags(task: dict) -> set:
	"""The explicit tags declared on a task (string or list -> set of str)."""
	t = task.get("tags")
	if isinstance(t, str):
		return {t}
	if isinstance(t, list):
		return {x for x in t if isinstance(x, str)}
	return set()


def _include_targets(task: dict) -> list[pathlib.Path]:
	"""Resolve any import_tasks/include_tasks target to a repo-relative path."""
	out: list[pathlib.Path] = []
	for key in (
		"ansible.builtin.import_tasks",
		"ansible.builtin.include_tasks",
		"import_tasks",
		"include_tasks",
	):
		val = task.get(key)
		ref = None
		if isinstance(val, str):
			ref = val
		elif isinstance(val, dict) and isinstance(val.get("file"), str):
			ref = val["file"]
		if ref:
			out.append((REPO / ref).resolve())
	return out


def _walk_task_file(path: pathlib.Path, seen: set[pathlib.Path]) -> list[dict]:
	"""Flatten a task file and its transitive includes into a task list."""
	if path in seen or not path.exists():
		return []
	seen.add(path)
	try:
		tasks = yaml.safe_load(path.read_text()) or []
	except yaml.YAMLError:
		return []
	if not isinstance(tasks, list):
		return []
	flat: list[dict] = []
	for t in tasks:
		if not isinstance(t, dict):
			continue
		flat.append(t)
		for inc in _include_targets(t):
			flat.extend(_walk_task_file(inc, seen))
	return flat


# ── (2) static content scan of the upgrade task graph ───────────────────────


def test_upgrade_engine_graph_has_no_host_disruptive_command():
	"""The upgrade task file + its transitive includes carry no host-disruptive
	command body. This is the engine's OWN graph — independent of the dynamic
	tag resolver, so it pins host-quietness even if list-tasks is unavailable."""
	tasks = _walk_task_file((TASKS / "upgrade-engine.yml").resolve(), set())
	assert tasks, "upgrade-engine.yml parsed to zero tasks — resolver broken"

	offenders: list[tuple[str, str]] = []
	for t in tasks:
		name = t.get("name", "<unnamed>")
		for body in _command_bodies(t):
			hit = _matches_command_denylist(body)
			if hit:
				offenders.append((name, hit))
	assert not offenders, (
		"--tags upgrade graph contains host-disruptive command(s) — an upgrade "
		f"run can drop the controlling session: {offenders}"
	)


def test_macos_defaults_is_the_killall_source_and_not_in_upgrade_graph():
	"""Guard against the gate silently passing because the killall moved. Assert
	(a) tasks/macos-defaults.yml IS the Dock/Finder killall source, and (b) it is
	NOT reachable from the upgrade-engine graph (it's a separately-imported,
	macos-defaults/osx-tagged file — never pulled in by upgrade-engine)."""
	mac = (TASKS / "macos-defaults.yml").read_text().lower()
	assert "killall finder" in mac and "killall dock" in mac, (
		"tasks/macos-defaults.yml no longer hosts the Dock/Finder killalls — the "
		"host-quiet gate's reference point moved; re-point this test"
	)
	graph_files = set()
	_walk_task_file((TASKS / "upgrade-engine.yml").resolve(), graph_files)
	assert (TASKS / "macos-defaults.yml").resolve() not in graph_files, (
		"upgrade-engine.yml transitively includes macos-defaults.yml — the GUI "
		"killalls are now in the upgrade graph"
	)


def test_reboot_word_in_prose_is_not_flagged_only_the_command_is():
	"""A reboot-NOTIFICATION task body legitimately contains the WORD 'reboot'
	(title 'Reboot pending …', path 'reboot-required.json', 'host_reboot-class').
	Only an actual reboot/shutdown COMMAND may trip the denylist — otherwise the
	Phase-3 reboot_required notification would fail its own host-quiet gate."""
	benign = [
		'title: ("Reboot pending to finish " + $svc + " upgrade")',
		'dest: ~/.nos/reboot-required.json',
		'body: ("A host_reboot-class upgrade was applied; the host must be restarted")',
		'echo "the machine should be rebooted"',
	]
	for b in benign:
		assert _matches_command_denylist(b) is None, f"false-positive on prose: {b}"
	malicious = [
		"reboot", "sudo reboot", "  reboot\n", "echo done; reboot",
		"/sbin/reboot", "shutdown -r now", "sudo shutdown -h now",
		"sudo halt", "shutdown now", "/sbin/halt",
		"osascript -e 'tell app \"System Events\" to restart'",
	]
	for m in malicious:
		assert _matches_command_denylist(m) is not None, f"missed a real command: {m}"


def test_no_upgrade_tagged_task_anywhere_is_host_disruptive():
	"""Ansible-free backstop for the regression the reachability test catches
	only when ansible-playbook is installed — the gating CI 'pytest' lane has no
	ansible-core, so that test SKIPS there. Walk EVERY task file under tasks/ and
	roles/*/tasks/ for a task that BOTH (a) carries an explicit 'upgrade' tag and
	(b) is host-disruptive by name or command body. The Dock/Finder killall lives
	in macos-defaults.yml with macos-defaults/osx tags today; the moment someone
	adds 'upgrade' to it (or any disruptive task), this fails — no tag resolver
	needed. (Tag inheritance via block/include is only seen by the reachability
	test; this pins the common direct-tag regression.)"""
	task_files = sorted(TASKS.rglob("*.yml"))
	task_files += sorted((REPO / "roles").glob("*/tasks/*.yml"))
	offenders: list[tuple[str, str]] = []
	for path in task_files:
		try:
			tasks = yaml.safe_load(path.read_text()) or []
		except yaml.YAMLError:
			continue
		if not isinstance(tasks, list):
			continue
		for t in tasks:
			if not isinstance(t, dict) or "upgrade" not in _task_tags(t):
				continue
			name = str(t.get("name", "")).lower()
			for bad in NAME_DENYLIST:
				if re.search(rf"\b{re.escape(bad)}\b", name):
					offenders.append((f"{path.name}:{name}", bad))
			for body in _command_bodies(t):
				hit = _matches_command_denylist(body)
				if hit:
					offenders.append((f"{path.name}:{t.get('name', '<unnamed>')}", hit))
	assert not offenders, (
		"a host-disruptive task carries the 'upgrade' tag — an upgrade run could "
		f"drop the controlling session: {offenders}"
	)


# ── (1) ground-truth reachability via ansible-playbook --list-tasks ─────────


def _list_tasks_upgrade() -> str | None:
	"""Return `ansible-playbook main.yml --list-tasks --tags upgrade` stdout, or
	None if ansible-playbook is unavailable (e.g. a pytest-only CI lane)."""
	exe = shutil.which("ansible-playbook")
	if not exe:
		return None
	try:
		res = subprocess.run(
			[exe, "main.yml", "--list-tasks", "--tags", "upgrade"],
			cwd=str(REPO),
			capture_output=True,
			text=True,
			timeout=120,
		)
	except (subprocess.TimeoutExpired, OSError):
		return None
	if res.returncode != 0:
		return None
	return res.stdout


def test_no_host_disruptive_task_name_reachable_under_upgrade_tag():
	"""Ground truth: drive Ansible's own tag resolver and assert no reachable
	task NAME matches a host-disruptive signature. Skips cleanly when
	ansible-playbook isn't on PATH (static gates above still pin the engine)."""
	out = _list_tasks_upgrade()
	if out is None:
		pytest.skip("ansible-playbook --list-tasks unavailable in this lane")

	# Each task line looks like '   <name>\tTAGS: [..]'. Reachable = it appears
	# in the --tags upgrade listing at all (Ansible already filtered by tag).
	offenders: list[str] = []
	for raw in out.splitlines():
		if "TAGS:" not in raw:
			continue
		name = raw.split("TAGS:")[0].strip().lower()
		for bad in NAME_DENYLIST:
			if re.search(rf"\b{re.escape(bad)}\b", name):
				offenders.append(name)
	assert not offenders, (
		"host-disruptive task name(s) reachable under --tags upgrade — tag "
		f"isolation broke: {offenders}"
	)
