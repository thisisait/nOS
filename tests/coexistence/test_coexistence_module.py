"""Unit tests for ``library/nos_coexistence.py``.

Cover:

* provision_track creates the compose override, the nginx vhost and
  records the track in state.yml,
* cutover atomically flips active and regenerates the vhost,
* cleanup refuses the active track unless force=true,
* TTL countdown / expiry logic (cleanup honors ``ttl_until``),
* port allocation math, port collision refusal,
* data-source clone_from dispatches to the correct strategy.

Tests intentionally mock the underlying shell (no docker / pg_dump run).
"""

from __future__ import annotations

import datetime
import importlib.util
import os
import pathlib
import sys
import types

import pytest

_HERE = pathlib.Path(__file__).resolve()
_REPO = _HERE.parents[2]


def _load_module(relpath: str, name: str) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, _REPO / relpath)
    assert spec and spec.loader, f"cannot load {relpath}"
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# module_utils first so library picks it up via sys.modules.
clone_mod = _load_module("module_utils/nos_coexistence_clone.py",
                         "module_utils.nos_coexistence_clone")
# Ensure the package path resolves too.
pkg = types.ModuleType("module_utils")
pkg.__path__ = [str(_REPO / "module_utils")]  # type: ignore[attr-defined]
sys.modules.setdefault("module_utils", pkg)
sys.modules["module_utils.nos_coexistence_clone"] = clone_mod

lib = _load_module("library/nos_coexistence.py", "nos_coexistence_lib")


# ---------------------------------------------------------------------------
# fixtures

@pytest.fixture
def tmp_env(tmp_path):
    """Build a self-contained fake nOS tree under tmp_path."""
    stacks_dir = tmp_path / "stacks"
    (stacks_dir / "observability" / "overrides").mkdir(parents=True)
    nginx_sites_dir = tmp_path / "nginx" / "servers"
    nginx_sites_dir.mkdir(parents=True)
    state_path = tmp_path / "state.yml"
    return {
        "tmp_path": tmp_path,
        "stacks_dir": str(stacks_dir),
        "nginx_sites_dir": str(nginx_sites_dir),
        "nginx_log_dir": str(tmp_path / "log"),
        "state_path": str(state_path),
    }


def _base_params(env, **overrides):
    params = {
        "action": "provision_track",
        "service": "grafana",
        "tag": "legacy",
        "version": "11.5.0",
        "base_port": 3000,
        "coexistence_port_offset": 10,
        "data_path": str(env["tmp_path"] / "data" / "grafana-legacy"),
        "stack": "observability",
        "stacks_dir": env["stacks_dir"],
        "nginx_sites_dir": env["nginx_sites_dir"],
        "nginx_log_dir": env["nginx_log_dir"],
        "state_path": env["state_path"],
        "domain": "grafana.dev.local",
        "web_service": True,
    }
    params.update(overrides)
    return params


def _no_port_in_use(host, port):  # pragma: no cover - trivial stub
    return False


# ---------------------------------------------------------------------------
# provision

def test_provision_creates_override_and_vhost_and_state(tmp_env):
    params = _base_params(tmp_env)
    result = lib.run_action(params, ctx={"port_probe": _no_port_in_use})

    assert result["changed"] is True
    rec = result["result"]
    assert rec["port"] == 3000
    assert os.path.exists(rec["compose_override"])
    assert os.path.exists(rec["nginx_vhost"])

    # Compose override mentions the service+tag and port.
    body = pathlib.Path(rec["compose_override"]).read_text()
    assert "grafana-legacy" in body
    assert "127.0.0.1:3000:3000" in body

    # Nginx vhost contains an upstream block for the tag.
    vhost = pathlib.Path(rec["nginx_vhost"]).read_text()
    assert "upstream grafana_legacy" in vhost
    assert "server 127.0.0.1:3000" in vhost

    # State records the track.
    import yaml
    state = yaml.safe_load(pathlib.Path(tmp_env["state_path"]).read_text())
    assert state["coexistence"]["grafana"]["active_track"] == "legacy"
    assert state["coexistence"]["grafana"]["tracks"][0]["port"] == 3000


def test_provision_second_track_allocates_offset_port(tmp_env):
    # First track
    lib.run_action(_base_params(tmp_env, tag="legacy"),
                   ctx={"port_probe": _no_port_in_use})
    # Second track inherits base_port, expects 3010
    result = lib.run_action(
        _base_params(tmp_env, tag="new",
                     data_path=str(tmp_env["tmp_path"] / "data" / "grafana-new")),
        ctx={"port_probe": _no_port_in_use},
    )
    assert result["result"]["port"] == 3010


def test_provision_refuses_duplicate_tag(tmp_env):
    lib.run_action(_base_params(tmp_env), ctx={"port_probe": _no_port_in_use})
    result = lib.run_action(_base_params(tmp_env),
                            ctx={"port_probe": _no_port_in_use})
    assert result.get("failed") is True
    assert "already exists" in result["msg"]


def test_provision_refuses_external_port_conflict(tmp_env):
    def always_busy(host, port):
        return True
    result = lib.run_action(_base_params(tmp_env),
                            ctx={"port_probe": always_busy})
    assert result.get("failed") is True
    assert "already bound" in result["msg"]


def test_provision_refuses_non_empty_data_dir_without_force(tmp_env):
    data = tmp_env["tmp_path"] / "data" / "grafana-legacy"
    data.mkdir(parents=True)
    (data / "existing").write_text("payload")
    result = lib.run_action(_base_params(tmp_env),
                            ctx={"port_probe": _no_port_in_use})
    assert result.get("failed") is True
    assert "non-empty" in result["msg"]


def test_provision_unsupported_service_rejected(tmp_env):
    result = lib.run_action(_base_params(tmp_env, service="mattermost"),
                            ctx={"port_probe": _no_port_in_use})
    assert result.get("failed") is True


# ---------------------------------------------------------------------------
# cutover

def test_cutover_flips_active_and_regenerates_vhost(tmp_env):
    # Provision two tracks
    lib.run_action(_base_params(tmp_env, tag="legacy"),
                   ctx={"port_probe": _no_port_in_use})
    lib.run_action(
        _base_params(tmp_env, tag="new",
                     version="12.0.0",
                     data_path=str(tmp_env["tmp_path"] / "data" / "grafana-new")),
        ctx={"port_probe": _no_port_in_use},
    )

    # Cutover
    result = lib.run_action({
        "action": "cutover",
        "service": "grafana",
        "target_tag": "new",
        "stacks_dir": tmp_env["stacks_dir"],
        "nginx_sites_dir": tmp_env["nginx_sites_dir"],
        "nginx_log_dir": tmp_env["nginx_log_dir"],
        "domain": "grafana.dev.local",
        "state_path": tmp_env["state_path"],
        "ttl_seconds": 3600,
    })
    assert result["changed"] is True
    assert result["result"]["previous_active"] == "legacy"
    assert result["result"]["new_active"] == "new"

    # Active upstream in the regenerated vhost should be `grafana_new`
    vhost = pathlib.Path(result["result"]["nginx_vhost"]).read_text()
    assert "set $nos_upstream grafana_new" in vhost

    # Previous track should be read_only and carry a ttl_until.
    import yaml
    state = yaml.safe_load(pathlib.Path(tmp_env["state_path"]).read_text())
    legacy = next(t for t in state["coexistence"]["grafana"]["tracks"]
                  if t["tag"] == "legacy")
    assert legacy["read_only"] is True
    assert "ttl_until" in legacy


def test_cutover_to_same_tag_is_noop(tmp_env):
    lib.run_action(_base_params(tmp_env, tag="legacy"),
                   ctx={"port_probe": _no_port_in_use})
    result = lib.run_action({
        "action": "cutover",
        "service": "grafana",
        "target_tag": "legacy",
        "stacks_dir": tmp_env["stacks_dir"],
        "nginx_sites_dir": tmp_env["nginx_sites_dir"],
        "nginx_log_dir": tmp_env["nginx_log_dir"],
        "state_path": tmp_env["state_path"],
    })
    assert result["changed"] is False
    assert result["result"]["noop"] is True


def test_cutover_unknown_target_fails(tmp_env):
    lib.run_action(_base_params(tmp_env, tag="legacy"),
                   ctx={"port_probe": _no_port_in_use})
    result = lib.run_action({
        "action": "cutover",
        "service": "grafana",
        "target_tag": "ghost",
        "stacks_dir": tmp_env["stacks_dir"],
        "nginx_sites_dir": tmp_env["nginx_sites_dir"],
        "state_path": tmp_env["state_path"],
    })
    assert result.get("failed") is True


# ---------------------------------------------------------------------------
# cleanup

def test_cleanup_refuses_active_track(tmp_env):
    lib.run_action(_base_params(tmp_env, tag="legacy"),
                   ctx={"port_probe": _no_port_in_use})
    result = lib.run_action({
        "action": "cleanup_track",
        "service": "grafana",
        "tag": "legacy",
        "stacks_dir": tmp_env["stacks_dir"],
        "nginx_sites_dir": tmp_env["nginx_sites_dir"],
        "state_path": tmp_env["state_path"],
    })
    assert result.get("failed") is True
    assert "active" in result["msg"]


def test_cleanup_with_force_removes_active_track(tmp_env):
    lib.run_action(_base_params(tmp_env, tag="legacy"),
                   ctx={"port_probe": _no_port_in_use})
    result = lib.run_action({
        "action": "cleanup_track",
        "service": "grafana",
        "tag": "legacy",
        "stacks_dir": tmp_env["stacks_dir"],
        "nginx_sites_dir": tmp_env["nginx_sites_dir"],
        "state_path": tmp_env["state_path"],
        "force": True,
    })
    assert result["changed"] is True
    import yaml
    state = yaml.safe_load(pathlib.Path(tmp_env["state_path"]).read_text())
    # last remaining track pruned → coexistence key removed
    assert "grafana" not in state.get("coexistence", {})


def test_cleanup_respects_ttl_countdown(tmp_env):
    # Provision legacy + new, cutover, then try cleaning legacy within TTL.
    lib.run_action(_base_params(tmp_env, tag="legacy"),
                   ctx={"port_probe": _no_port_in_use})
    lib.run_action(
        _base_params(tmp_env, tag="new",
                     version="12.0.0",
                     data_path=str(tmp_env["tmp_path"] / "data" / "grafana-new")),
        ctx={"port_probe": _no_port_in_use},
    )
    lib.run_action({
        "action": "cutover",
        "service": "grafana",
        "target_tag": "new",
        "stacks_dir": tmp_env["stacks_dir"],
        "nginx_sites_dir": tmp_env["nginx_sites_dir"],
        "state_path": tmp_env["state_path"],
        "ttl_seconds": 3600,
    })

    # TTL is in the future → cleanup refuses.
    result = lib.run_action({
        "action": "cleanup_track",
        "service": "grafana",
        "tag": "legacy",
        "stacks_dir": tmp_env["stacks_dir"],
        "nginx_sites_dir": tmp_env["nginx_sites_dir"],
        "state_path": tmp_env["state_path"],
    })
    assert result.get("failed") is True
    assert "ttl_until" in result["msg"]


def test_cleanup_bypass_ttl_with_respect_ttl_false(tmp_env):
    lib.run_action(_base_params(tmp_env, tag="legacy"),
                   ctx={"port_probe": _no_port_in_use})
    lib.run_action(
        _base_params(tmp_env, tag="new",
                     version="12.0.0",
                     data_path=str(tmp_env["tmp_path"] / "data" / "grafana-new")),
        ctx={"port_probe": _no_port_in_use},
    )
    lib.run_action({
        "action": "cutover",
        "service": "grafana",
        "target_tag": "new",
        "stacks_dir": tmp_env["stacks_dir"],
        "nginx_sites_dir": tmp_env["nginx_sites_dir"],
        "state_path": tmp_env["state_path"],
        "ttl_seconds": 3600,
    })

    # Cleanup legacy, ignoring TTL.
    result = lib.run_action({
        "action": "cleanup_track",
        "service": "grafana",
        "tag": "legacy",
        "stacks_dir": tmp_env["stacks_dir"],
        "nginx_sites_dir": tmp_env["nginx_sites_dir"],
        "state_path": tmp_env["state_path"],
        "respect_ttl": False,
    })
    assert result["changed"] is True


def test_cleanup_expired_ttl_allows_removal(tmp_env):
    # Craft a state file with an expired TTL manually.
    import yaml
    expired = (datetime.datetime.now(tz=datetime.timezone.utc)
               - datetime.timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    state = {
        "schema_version": 1,
        "coexistence": {
            "grafana": {
                "active_track": "new",
                "tracks": [
                    {"tag": "legacy", "version": "11.5.0", "port": 3000,
                     "data_path": str(tmp_env["tmp_path"] / "data" / "grafana-legacy"),
                     "stack": "observability", "ttl_until": expired},
                    {"tag": "new", "version": "12.0.0", "port": 3010,
                     "data_path": str(tmp_env["tmp_path"] / "data" / "grafana-new"),
                     "stack": "observability"},
                ],
            },
        },
    }
    pathlib.Path(tmp_env["state_path"]).write_text(yaml.safe_dump(state))

    result = lib.run_action({
        "action": "cleanup_track",
        "service": "grafana",
        "tag": "legacy",
        "stacks_dir": tmp_env["stacks_dir"],
        "nginx_sites_dir": tmp_env["nginx_sites_dir"],
        "state_path": tmp_env["state_path"],
    })
    assert result["changed"] is True


# ---------------------------------------------------------------------------
# list_tracks

def test_list_tracks_returns_coex_section(tmp_env):
    lib.run_action(_base_params(tmp_env, tag="legacy"),
                   ctx={"port_probe": _no_port_in_use})
    result = lib.run_action({
        "action": "list_tracks",
        "state_path": tmp_env["state_path"],
        "stacks_dir": tmp_env["stacks_dir"],
        "nginx_sites_dir": tmp_env["nginx_sites_dir"],
    })
    assert result["changed"] is False
    assert "grafana" in result["result"]["tracks"]


# ---------------------------------------------------------------------------
# clone_from integration (happy path)

def test_provision_clone_from_invokes_strategy(tmp_env, monkeypatch):
    # Create the "source" track + seed some data.
    legacy_params = _base_params(tmp_env, tag="legacy")
    lib.run_action(legacy_params, ctx={"port_probe": _no_port_in_use})
    src = pathlib.Path(legacy_params["data_path"])
    src.mkdir(parents=True, exist_ok=True)
    (src / "marker").write_text("hello")

    # Spy on the clone module.
    called = {}

    def fake_clone(method, spec, ctx=None):
        called["method"] = method
        called["spec"] = spec
        # Actually copy so downstream checks work.
        os.makedirs(spec["dst_path"], exist_ok=True)
        return {"success": True, "changed": True, "method": method,
                "error": None, "details": spec}

    monkeypatch.setattr(clone_mod, "clone", fake_clone)
    # Also patch the reference the library captured at import time.
    monkeypatch.setattr(lib, "_clone_module", clone_mod)

    result = lib.run_action(
        _base_params(tmp_env, tag="new",
                     version="12.0.0",
                     data_path=str(tmp_env["tmp_path"] / "data" / "grafana-new"),
                     data_source="clone_from:legacy"),
        ctx={"port_probe": _no_port_in_use},
    )
    assert result["changed"] is True
    assert called["method"] == "cp_recursive"
    assert called["spec"]["src_path"].endswith("grafana-legacy")
    assert called["spec"]["dst_path"].endswith("grafana-new")
