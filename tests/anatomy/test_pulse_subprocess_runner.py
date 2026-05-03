"""Tests for pulse.runners.subprocess.execute()."""

from __future__ import annotations

import sys

import pytest

from pulse.runners.subprocess import execute


def test_execute_success_captures_stdout():
    r = execute(sys.executable, ["-c", "print('hi')"], timeout_s=5)
    assert r.exit_code == 0
    assert "hi" in r.stdout_tail
    assert r.stderr_tail == ""
    assert r.timed_out is False


def test_execute_nonzero_exit_captured():
    r = execute(sys.executable, ["-c", "import sys; sys.exit(7)"], timeout_s=5)
    assert r.exit_code == 7
    assert r.timed_out is False


def test_execute_stderr_captured():
    r = execute(sys.executable, ["-c", "import sys; print('err', file=sys.stderr)"],
                timeout_s=5)
    assert r.exit_code == 0
    assert "err" in r.stderr_tail


def test_execute_timeout_returns_minus_9():
    """SIGKILL-on-timeout convention → exit_code == -9, timed_out == True."""
    r = execute(sys.executable, ["-c", "import time; time.sleep(10)"],
                timeout_s=0.5)
    assert r.exit_code == -9
    assert r.timed_out is True
    assert r.duration_s >= 0.5


def test_execute_command_not_found_returns_127():
    r = execute("/no/such/binary/exists", [], timeout_s=5)
    assert r.exit_code == 127
    assert r.timed_out is False
    assert "command not found" in r.stderr_tail.lower()


def test_execute_env_passed():
    r = execute(sys.executable,
                ["-c", "import os; print(os.environ.get('PULSE_TEST_VAR', 'unset'))"],
                timeout_s=5,
                env={"PULSE_TEST_VAR": "set-from-test"})
    assert r.exit_code == 0
    assert "set-from-test" in r.stdout_tail
