"""Anatomy gate: the detached upgrade launcher (Phase 3, 2026-06-20).

`tools/nos-upgrade-detached.sh` runs `ansible-playbook --tags upgrade` DETACHED
from the controlling TTY so a SESSION-RISK upgrade (reset.scope host_app /
host_reboot) survives the operator's terminal/IDE dying mid-run. This gate pins
the contract that makes that work and keeps the launcher host-quiet:

  1. The script parses clean under `bash -n`.
  2. It passes `upgrade_confirmed=true` — the engine's session-risk pre-apply
     pause keys off this to NOT block the headless run.
  3. It threads the service into `-e upgrade_service=...`.
  4. It detaches: a macOS branch uses `caffeinate` (keep-alive) + `nohup`, and
     the Linux/fallback path uses `setsid` + `nohup` (a new session leader that
     survives logout). Every exec branch is BACKGROUNDED and the script returns
     immediately (it must not block its caller).
  5. It writes its log + pidfile under ~/.nos (the runtime sidecar).
  6. It refuses `blank=true` and requires no sudo (never invokes `sudo`).
  7. It is host-disruptive-verb-free except for LAUNCHING the playbook: no
     `killall` / `reboot` / `shutdown` of its own.

If this gate FAILS the launcher cannot safely carry a session-risk upgrade —
that is a real finding, not a flaky test. See
docs/archive/upgrade-reset-scope-and-session-safety.md §"Execution side".
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / "tools" / "nos-upgrade-detached.sh"


def _body() -> str:
	assert SCRIPT.exists(), f"launcher missing: {SCRIPT}"
	return SCRIPT.read_text()


def _code() -> str:
	"""The launcher with full-line `#` comments stripped — so denylist scans for
	disruptive verbs / `sudo` see only EXECUTABLE lines, not the header prose that
	legitimately *names* those verbs to document what the script must NOT do."""
	lines = []
	for raw in _body().splitlines():
		if raw.lstrip().startswith("#"):
			continue
		lines.append(raw)
	return "\n".join(lines)


def test_script_exists_and_is_executable():
	assert SCRIPT.exists(), f"launcher missing: {SCRIPT}"
	assert SCRIPT.stat().st_mode & 0o111, "launcher is not executable (chmod +x)"


def test_bash_n_parses_clean():
	"""`bash -n` must parse the launcher with no syntax error."""
	bash = shutil.which("bash")
	if not bash:
		pytest.skip("bash not on PATH in this lane")
	res = subprocess.run(
		[bash, "-n", str(SCRIPT)],
		capture_output=True,
		text=True,
		timeout=30,
	)
	assert res.returncode == 0, f"bash -n failed:\n{res.stderr}"


def test_has_strict_mode_and_shebang():
	body = _body()
	assert body.startswith("#!/usr/bin/env bash"), "missing bash shebang"
	assert "set -euo pipefail" in body, "missing `set -euo pipefail`"


def test_passes_upgrade_confirmed_true():
	"""The headless run MUST pre-confirm so the engine's session-risk pause does
	not block it (the operator already chose detached)."""
	body = _body()
	assert re.search(r"upgrade_confirmed=true", body), (
		"launcher does not pass upgrade_confirmed=true — the engine's "
		"session-risk pre-apply pause would hang the TTY-less run"
	)


def test_threads_service_into_extra_vars():
	body = _body()
	assert re.search(r"upgrade_service=", body), (
		"launcher does not pass -e upgrade_service=<service>"
	)


def test_uses_tags_upgrade():
	body = _body()
	assert re.search(r"--tags\s+upgrade", body), "launcher does not target --tags upgrade"


def test_macos_branch_uses_caffeinate():
	"""The macOS path must keep the host awake/alive for the run's lifetime."""
	body = _body()
	assert "caffeinate" in body, "macOS branch does not use caffeinate (idle-sleep keep-alive)"
	# caffeinate is the macOS branch — guard it behind a uname/Darwin check.
	assert re.search(r"uname\s+-s", body), "no `uname -s` platform branch around caffeinate"
	assert "Darwin" in body, "no Darwin branch guarding the caffeinate path"


def test_detaches_from_tty():
	"""nohup + setsid must detach the run from the controlling TTY (a new session
	leader) so a session death / logout does not SIGHUP it."""
	body = _body()
	assert "nohup" in body, "expected a nohup detach path"
	assert "setsid" in body, "expected a setsid (new session leader) detach path"


def test_writes_log_and_pid_under_nos_sidecar():
	body = _body()
	assert re.search(r"\.nos", body), "launcher does not write under ~/.nos"
	assert re.search(r"upgrade-\$\{?SERVICE", body) or "upgrade-${SERVICE}" in body, (
		"launcher log/pid names do not include the service"
	)
	assert "PIDFILE" in body or ".pid" in body, "launcher does not write a pidfile"


def test_refuses_blank_and_no_sudo():
	body = _body()
	assert "blank=true" in body, "launcher does not guard against blank=true"
	assert re.search(r"refusing", body, re.IGNORECASE), "no refusal path for blank=true"
	for tok in ("remove=data", "remove=deep", "remove=all", "uninstall=true"):
		assert tok in body, f"launcher glob lost the '{tok}' refusal token"
	# The launcher must never escalate. Match `sudo` only at a COMMAND position
	# (statement start, or after a shell separator) so a diagnostic echo that
	# merely mentions the word — e.g. "needs sudo + a human" — is not a false hit.
	assert not re.search(
		r"(?:^|[;&|]|\b(?:then|do|else)\b)\s*sudo\b",
		_code(),
		re.MULTILINE,
	), "launcher invokes sudo as a command — it must not escalate"


def test_no_self_host_disruptive_verb():
	"""The launcher LAUNCHES the playbook but owns no disruptive verb itself —
	no killall / reboot / shutdown in its body."""
	code = _code()
	for bad in (r"\bkillall\b", r"\breboot\b", r"\bshutdown\b"):
		assert not re.search(bad, code), (
			f"launcher contains a host-disruptive verb matching {bad!r} — it must "
			"only LAUNCH the playbook, never disrupt the host itself"
		)


def test_passes_auto_upgrade_true():
	"""A detached run must ALSO bypass the breaking/security pre-apply pause (keyed
	off auto_upgrade), not only the session-risk pause (keyed off
	upgrade_confirmed) — else a detached BREAKING upgrade still hits a prompt."""
	body = _body()
	assert re.search(r"auto_upgrade=true", body), (
		"launcher does not pass auto_upgrade=true — a detached run of a BREAKING "
		"recipe would still block on the breaking-confirm pause"
	)


def test_backgrounds_and_returns_immediately():
	"""The load-bearing 'detached' contract: every exec branch must BACKGROUND the
	run (trailing `&`) with stdin from /dev/null, capture the real PID via `$!`,
	and the script must reach `exit 0` — else the launcher blocks its caller (and a
	future Wing 'plan -> detached' button would hang the web request). A mutant
	that drops the trailing `&` parses clean under `bash -n` yet blocks forever;
	this pins the contract that the other assertions miss."""
	code = _code()
	# The real exec branches invoke ansible-playbook with the PLAY_ARGS array;
	# filter on that to skip the `command -v` check and the usage() heredoc prose.
	exec_lines = [
		ln for ln in code.splitlines()
		if "ansible-playbook" in ln and "PLAY_ARGS" in ln
	]
	assert exec_lines, "no ansible-playbook exec branch found"
	for ln in exec_lines:
		assert ln.rstrip().endswith("&"), (
			f"exec branch is not backgrounded (no trailing &): {ln.strip()!r}"
		)
		assert "</dev/null" in ln, (
			f"exec branch does not redirect stdin from /dev/null: {ln.strip()!r}"
		)
	assert "PID=$!" in code, "launcher does not capture the backgrounded PID via $!"
	assert re.search(r"^\s*exit 0\s*$", code, re.MULTILINE), (
		"launcher does not reach `exit 0` — it may block instead of returning"
	)
