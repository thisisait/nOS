"""Shared pytest fixtures for callback-plugin tests.

Adds the repo root to ``sys.path`` so the ``callback_plugins`` package can be
imported from anywhere, and provides a lightweight fake-Ansible result /
task / playbook set so we don't need Ansible installed to unit-test the
plugin.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "callback_plugins"))


# --------------------------------------------------------------------------- #
# Fake Ansible objects                                                        #
# --------------------------------------------------------------------------- #

class FakePlaybook:
    def __init__(self, file_name="main.yml"):
        self._file_name = file_name


class FakePlay:
    def __init__(self, name="test play", vars_=None):
        self.name = name
        self._vars = vars_ or {}

    def get_vars(self):
        return self._vars


class FakeRole:
    def __init__(self, name):
        self._role_name = name


class FakeTask:
    _counter = 0

    def __init__(self, name, role=None):
        FakeTask._counter += 1
        self._name = name
        self._uuid = "t-{:d}".format(FakeTask._counter)
        self._role = FakeRole(role) if role else None

    def get_name(self):
        return self._name


class FakeHost:
    def __init__(self, name="localhost"):
        self.name = name


class FakeResult:
    def __init__(self, task, result=None, host="localhost"):
        self._task = task
        self._result = result or {}
        self._host = FakeHost(host)


class FakeStats:
    def __init__(self, per_host):
        self.processed = {h: True for h in per_host}
        self._per_host = per_host

    def summarize(self, host):
        return self._per_host[host]


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #

@pytest.fixture
def repo_root():
    return REPO_ROOT


@pytest.fixture
def event_schema(repo_root):
    path = repo_root / "state" / "schema" / "event.schema.json"
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture
def validator(event_schema):
    jsonschema = pytest.importorskip("jsonschema")
    return jsonschema.Draft7Validator(event_schema)


@pytest.fixture(autouse=True)
def _reset_env(monkeypatch):
    """Strip telemetry env vars before each test so activation is explicit."""
    for k in list(os.environ):
        if k.startswith("GLASSWING_") or k == "NOS_TELEMETRY_ENABLED":
            monkeypatch.delenv(k, raising=False)
    yield


@pytest.fixture
def fresh_plugin(monkeypatch, tmp_path):
    """Import a fresh CallbackModule with env vars pointing at a tmp sqlite."""
    monkeypatch.setenv("NOS_TELEMETRY_ENABLED", "1")
    monkeypatch.setenv("GLASSWING_EVENTS_SQLITE_FALLBACK",
                       str(tmp_path / "fallback.db"))
    monkeypatch.setenv("GLASSWING_EVENTS_URL",
                       "http://test.invalid/api/v1/events")
    monkeypatch.setenv("GLASSWING_EVENTS_BATCH_SIZE", "100")
    monkeypatch.setenv("GLASSWING_EVENTS_FLUSH_INTERVAL_SEC", "3600")

    # Reimport to pick up env.
    import importlib
    mod = importlib.import_module("glasswing_telemetry")
    importlib.reload(mod)
    plugin = mod.CallbackModule()
    plugin._finalize_activation({"glasswing_telemetry_enabled": True})
    return mod, plugin
