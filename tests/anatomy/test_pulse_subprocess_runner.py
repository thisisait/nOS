"""Tests for pulse.runners.subprocess.execute() + the SEC H-PULSE1 allowlist.

The run-behaviour tests invoke sys.executable, which resolves to a Homebrew
Cellar / hostedtoolcache path OUTSIDE the production command allowlist
(`/opt/homebrew/bin/` etc. hold symlinks). They use the `permit_all` fixture so
they exercise execute()'s run logic; the allowlist + env-scoping (SEC H-PULSE1 /
M-PULSE2, 2026-05-24) get their own dedicated tests below.
"""

from __future__ import annotations

import sys

import pytest

from pulse.runners import subprocess as sub
from pulse.runners.subprocess import execute, validate_command, CommandRejected


@pytest.fixture
def permit_all(monkeypatch):
    """Bypass the command allowlist so run-behaviour tests can use
    `python -c "<code>"` (which legitimately fails the production arg-regex —
    spaces/quotes/parens). The allowlist + arg-regex are tested directly below."""
    monkeypatch.setattr(sub, "validate_command", lambda command, args: None)


# ── run behaviour ────────────────────────────────────────────────────────────
def test_execute_success_captures_stdout(permit_all):
    r = execute(sys.executable, ["-c", "print('hi')"], timeout_s=5)
    assert r.exit_code == 0
    assert "hi" in r.stdout_tail
    assert r.stderr_tail == ""
    assert r.timed_out is False


def test_execute_nonzero_exit_captured(permit_all):
    r = execute(sys.executable, ["-c", "import sys; sys.exit(7)"], timeout_s=5)
    assert r.exit_code == 7
    assert r.timed_out is False


def test_execute_stderr_captured(permit_all):
    r = execute(sys.executable, ["-c", "import sys; print('err', file=sys.stderr)"],
                timeout_s=5)
    assert r.exit_code == 0
    assert "err" in r.stderr_tail


def test_execute_timeout_returns_minus_9(permit_all):
    """SIGKILL-on-timeout convention → exit_code == -9, timed_out == True."""
    r = execute(sys.executable, ["-c", "import time; time.sleep(10)"], timeout_s=0.5)
    assert r.exit_code == -9
    assert r.timed_out is True
    assert r.duration_s >= 0.5


def test_execute_command_not_found_returns_127(permit_all):
    r = execute("/no/such/binary/exists", [], timeout_s=5)
    assert r.exit_code == 127
    assert r.timed_out is False
    assert "command not found" in r.stderr_tail.lower()


def test_execute_env_passed(permit_all):
    r = execute(sys.executable,
                ["-c", "import os; print(os.environ.get('PULSE_TEST_VAR', 'unset'))"],
                timeout_s=5,
                env={"PULSE_TEST_VAR": "set-from-test"})
    assert r.exit_code == 0
    assert "set-from-test" in r.stdout_tail


# ── SEC H-PULSE1: execution-boundary allowlist ───────────────────────────────
def test_validate_rejects_shell_interpreter():
    with pytest.raises(CommandRejected):
        validate_command("/opt/homebrew/bin/bash", [])


def test_validate_rejects_non_allowlisted_path():
    with pytest.raises(CommandRejected):
        validate_command("/etc/evil", [])


def test_validate_rejects_relative_path():
    with pytest.raises(CommandRejected):
        validate_command("gitleaks", [])


def test_validate_rejects_shell_meta_arg():
    with pytest.raises(CommandRejected):
        validate_command("/opt/homebrew/bin/gitleaks", ["; rm -rf /"])


def test_validate_accepts_allowlisted_command():
    validate_command("/opt/homebrew/bin/gitleaks", ["detect", "--source=/x"])  # no raise


def test_execute_rejects_non_allowlisted_returns_126():
    """Default allowlist (no permit_all): /bin/echo is not allowlisted."""
    r = execute("/bin/echo", ["hi"], timeout_s=5)
    assert r.exit_code == 126
    assert "allowlist" in r.stderr_tail.lower()


# ── SEC M-PULSE2: child-env scoping ──────────────────────────────────────────
def test_execute_strips_secret_env(permit_all, monkeypatch):
    monkeypatch.setenv("WING_API_TOKEN", "super-secret")
    r = execute(sys.executable,
                ["-c", "import os; print(os.environ.get('WING_API_TOKEN', 'ABSENT'))"],
                timeout_s=5)
    assert r.exit_code == 0
    assert "ABSENT" in r.stdout_tail


def test_execute_blocks_loader_env(permit_all):
    r = execute(sys.executable,
                ["-c", "import os; print(os.environ.get('DYLD_INSERT_LIBRARIES', 'BLOCKED'))"],
                timeout_s=5,
                env={"DYLD_INSERT_LIBRARIES": "/evil.dylib"})
    assert r.exit_code == 0
    assert "BLOCKED" in r.stdout_tail
