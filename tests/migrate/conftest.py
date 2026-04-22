"""Test scaffolding for the nos_migrate engine.

Adds repo root to sys.path so ``import module_utils.nos_migrate_engine``
works without Ansible's plugin loader, and provides shared fixtures:

  * ``state_client`` — in-memory dict-backed state store that mimics the
    nos_state client contract (get/set via dotted paths).
  * ``authentik_client`` — in-memory fake with groups / oidc clients.
  * ``base_ctx``       — engine ctx dict pre-wired to a tmp state path.
  * ``cmd_recorder``   — captures subprocess commands the engine would run.
"""

from __future__ import absolute_import, division, print_function

import os
import sys

import pytest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


# ---------------------------------------------------------------------------
# In-memory state client that mirrors the nos_state dotted-path contract.

class FakeStateClient(object):
    def __init__(self, initial=None):
        self.data = dict(initial or {})

    def _split(self, dotted):
        return [p for p in str(dotted).split(".") if p]

    def get(self, dotted, default=None):
        cur = self.data
        for p in self._split(dotted):
            if not isinstance(cur, dict) or p not in cur:
                return default
            cur = cur[p]
        return cur

    def set(self, dotted, value):
        parts = self._split(dotted)
        if not parts:
            return False
        cur = self.data
        for p in parts[:-1]:
            nxt = cur.get(p)
            if not isinstance(nxt, dict):
                nxt = {}
                cur[p] = nxt
            cur = nxt
        prior = cur.get(parts[-1])
        if prior == value:
            return False
        cur[parts[-1]] = value
        return True


# ---------------------------------------------------------------------------
# Fake Authentik client.  Mirrors a handful of nos_authentik methods.

class FakeAuthentikClient(object):
    def __init__(self):
        self.groups = {}            # name -> {"members": [...], "policies": [...]}
        self.oidc_clients = {}      # name -> {...}
        self.calls = []

    # --- queries ------------------------------------------------------
    def get_group(self, name):
        return self.groups.get(name)

    def list_groups(self):
        return [dict(name=n, **meta) for n, meta in self.groups.items()]

    def get_oidc_client(self, name):
        return self.oidc_clients.get(name)

    def list_oidc_clients(self):
        return [dict(name=n, **meta) for n, meta in self.oidc_clients.items()]

    def wait_api_reachable(self, timeout_sec=10):
        self.calls.append(("wait_api_reachable", timeout_sec))
        return True

    # --- mutations ----------------------------------------------------
    def rename_group_prefix(self, from_prefix, to_prefix,
                            preserve_members=True, preserve_policies=True):
        self.calls.append(("rename_group_prefix", from_prefix, to_prefix))
        renamed = []
        for name in list(self.groups.keys()):
            if name.startswith(from_prefix):
                new_name = to_prefix + name[len(from_prefix):]
                self.groups[new_name] = self.groups.pop(name)
                renamed.append((name, new_name))
        return {"success": True, "changed": bool(renamed), "result": {"renamed": renamed}}

    def rename_oidc_client_prefix(self, from_prefix, to_prefix):
        self.calls.append(("rename_oidc_client_prefix", from_prefix, to_prefix))
        renamed = []
        for name in list(self.oidc_clients.keys()):
            if name.startswith(from_prefix):
                new_name = to_prefix + name[len(from_prefix):]
                self.oidc_clients[new_name] = self.oidc_clients.pop(name)
                renamed.append((name, new_name))
        return {"success": True, "changed": bool(renamed), "result": {"renamed": renamed}}

    def migrate_members(self, from_group, to_group):
        self.calls.append(("migrate_members", from_group, to_group))
        src = self.groups.get(from_group, {})
        dst = self.groups.setdefault(to_group, {"members": [], "policies": []})
        dst["members"] = list(set(dst.get("members", []) + src.get("members", [])))
        return {"success": True, "changed": True}


# ---------------------------------------------------------------------------
# Subprocess recorder: captures every cmd passed to handlers.

class CmdRecorder(object):
    def __init__(self, rc_map=None):
        """rc_map: dict keyed by tuple(cmd) → FakeCompletedProcess, or a
        callable returning one."""
        self.calls = []
        self.rc_map = rc_map or {}

    def __call__(self, cmd):
        self.calls.append(list(cmd))
        key = tuple(cmd)
        entry = self.rc_map.get(key)
        if callable(entry):
            return entry(cmd)
        if entry is not None:
            return entry
        return _FakeProc(0, "", "")


class _FakeProc(object):
    def __init__(self, rc, stdout="", stderr=""):
        self.returncode = rc
        self.stdout = stdout
        self.stderr = stderr


# ---------------------------------------------------------------------------
# Fixtures

@pytest.fixture
def fake_proc():
    return _FakeProc


@pytest.fixture
def state_client():
    return FakeStateClient({"schema_version": 1})


@pytest.fixture
def authentik_client():
    return FakeAuthentikClient()


@pytest.fixture
def cmd_recorder():
    return CmdRecorder()


@pytest.fixture
def base_ctx(tmp_path, state_client, authentik_client, cmd_recorder):
    """Engine ctx dict with test-safe overrides."""
    return {
        "dry_run": False,
        "state_client": state_client,
        "state_path": str(tmp_path / "state.yml"),
        "authentik_client": authentik_client,
        "run_cmd": cmd_recorder,
        "uid": 501,
        "launchagents_dir": str(tmp_path / "LaunchAgents"),
    }
