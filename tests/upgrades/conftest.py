"""Test scaffolding for upgrade recipes + engine action handlers.

Adds repo root to ``sys.path`` and exposes shared fixtures for the four
upgrade action modules (backup, http_ops, compose_ops, custom_module).
"""

from __future__ import absolute_import, division, print_function

import os
import sys

import pytest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


UPGRADES_DIR = os.path.join(ROOT, "upgrades")
SCHEMA_PATH = os.path.join(ROOT, "state", "schema", "upgrade.schema.json")


class _FakeProc(object):
    def __init__(self, rc=0, stdout="", stderr=""):
        self.returncode = rc
        self.stdout = stdout
        self.stderr = stderr


class CmdRecorder(object):
    def __init__(self, rc_map=None):
        self.calls = []
        self.rc_map = rc_map or {}

    def __call__(self, cmd, cwd=None):
        self.calls.append({"cmd": list(cmd), "cwd": cwd})
        key = tuple(cmd)
        entry = self.rc_map.get(key)
        if callable(entry):
            return entry(cmd, cwd)
        if entry is not None:
            return entry
        return _FakeProc(0, "", "")


class FakeHttp(object):
    def __init__(self, responses=None):
        """responses: list of (status, body_bytes) tuples or a callable."""
        self.calls = []
        self.responses = list(responses or [])

    def __call__(self, url, method="GET", headers=None, verify=False, timeout=10):
        self.calls.append({
            "url": url, "method": method, "headers": dict(headers or {}),
            "verify": verify, "timeout": timeout,
        })
        if callable(self.responses):
            return self.responses(url=url)
        if self.responses:
            return self.responses.pop(0)
        return (200, b"{}")


class FakeTcp(object):
    def __init__(self, sequence=None):
        """sequence: list of booleans, consumed one per call."""
        self.calls = []
        self.sequence = list(sequence) if sequence is not None else [True]

    def __call__(self, host, port, timeout=5):
        self.calls.append({"host": host, "port": port, "timeout": timeout})
        if self.sequence:
            return self.sequence.pop(0)
        return True


@pytest.fixture
def cmd_recorder():
    return CmdRecorder()


@pytest.fixture
def fake_http():
    return FakeHttp()


@pytest.fixture
def fake_tcp():
    return FakeTcp()


@pytest.fixture
def base_ctx(tmp_path, cmd_recorder):
    return {
        "dry_run": False,
        "run_cmd": cmd_recorder,
        "backup_root": str(tmp_path / "backups"),
        "stacks_dir": str(tmp_path / "stacks"),
        "upgrade_id": "test-upgrade",
        "vars": {},
        "sleep": lambda _s: None,    # tests don't actually sleep
    }
