"""Gate (B2): the coexistence lifecycle state machine — promote / deactivate /
cancel — keeps its load-bearing invariants.

Pins the three constraints the Lifecycle API (design §5) is built on:

* **one-primary invariant** — promote_track flips the active_track AND demotes
  the prior primary to role=secondary in the SAME state write, so there is
  never more than one role='primary' track, and role='primary' ⟺ active=1
  (the legacy pointer every existing reader keys off).
* **deactivate-primary refusal** — deactivate_track refuses the current primary
  without force (G-DEACTIVATE-NOT-PRIMARY) and refuses the only live track
  (G-DEACTIVATE-LAST). A non-primary secondary deactivates cleanly.
* **cancel-only-planned** — bin/planned-coexistence.php --cancel flips a
  status=planned row to cancelled but REFUSES (exit 1) when there is no planned
  row (an applied track must go deactivate → cleanup, not cancel).

The module half runs pure-python (no docker / nginx); the cancel half drives
the real PHP CLI against a synthetic wing.db, skipped if php is absent.
"""

from __future__ import annotations

import importlib.util
import pathlib
import shutil
import sqlite3
import subprocess
import sys
import types

import pytest
import yaml

_HERE = pathlib.Path(__file__).resolve()
_REPO = _HERE.parents[2]
_ANATOMY = _REPO / "files" / "anatomy"


# --------------------------------------------------------------------------- #
# load library/nos_coexistence.py the same way tests/coexistence does          #
# --------------------------------------------------------------------------- #

def _load_module(relpath: str, name: str) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, _REPO / relpath)
    assert spec and spec.loader, f"cannot load {relpath}"
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_clone = _load_module("files/anatomy/module_utils/nos_coexistence_clone.py",
                      "module_utils.nos_coexistence_clone")
_pkg = types.ModuleType("module_utils")
_pkg.__path__ = [str(_ANATOMY / "module_utils")]  # type: ignore[attr-defined]
sys.modules.setdefault("module_utils", _pkg)
sys.modules["module_utils.nos_coexistence_clone"] = _clone

lib = _load_module("files/anatomy/library/nos_coexistence.py",
                   "nos_coexistence_lib_statemachine")


def _no_port(host, port):  # always reachable → health guard never refuses
    return False


def _port_up(host, port):  # always up
    return True


# --------------------------------------------------------------------------- #
# fixtures                                                                     #
# --------------------------------------------------------------------------- #

@pytest.fixture
def env(tmp_path):
    stacks = tmp_path / "stacks"
    (stacks / "observability" / "overrides").mkdir(parents=True)
    nginx = tmp_path / "nginx" / "servers"
    nginx.mkdir(parents=True)
    return {
        "tmp_path": tmp_path,
        "stacks_dir": str(stacks),
        "nginx_sites_dir": str(nginx),
        "nginx_log_dir": str(tmp_path / "log"),
        "state_path": str(tmp_path / "state.yml"),
    }


def _provision(env, tag, version, **extra):
    params = {
        "action": "provision_track",
        "service": "grafana",
        "tag": tag,
        "version": version,
        "base_port": 3000,
        "coexistence_port_offset": 10,
        "data_path": str(env["tmp_path"] / "data" / f"grafana-{tag}"),
        "stack": "observability",
        "stacks_dir": env["stacks_dir"],
        "nginx_sites_dir": env["nginx_sites_dir"],
        "nginx_log_dir": env["nginx_log_dir"],
        "state_path": env["state_path"],
        "domain": "grafana.dev.local",
        "web_service": True,
    }
    params.update(extra)
    return lib.run_action(params, ctx={"port_probe": _no_port})


def _read_state(env):
    return yaml.safe_load(pathlib.Path(env["state_path"]).read_text())


def _tracks(env, service="grafana"):
    return _read_state(env)["coexistence"][service]["tracks"]


def _active(env, service="grafana"):
    return _read_state(env)["coexistence"][service]["active_track"]


def _common(env, **extra):
    base = {
        "service": "grafana",
        "stacks_dir": env["stacks_dir"],
        "nginx_sites_dir": env["nginx_sites_dir"],
        "nginx_log_dir": env["nginx_log_dir"],
        "domain": "grafana.dev.local",
        "state_path": env["state_path"],
        "dry_run": False,
    }
    base.update(extra)
    return base


# --------------------------------------------------------------------------- #
# provision stamps role/lifecycle: first track is primary, rest provisioned    #
# --------------------------------------------------------------------------- #

def test_provision_first_track_is_primary_rest_provisioned(env):
    _provision(env, "v16", "16")
    _provision(env, "v17", "17",
               data_path=str(env["tmp_path"] / "data" / "grafana-v17"))
    tracks = {t["tag"]: t for t in _tracks(env)}
    assert tracks["v16"]["role"] == "primary"
    assert tracks["v16"]["lifecycle"] == "primary"
    assert tracks["v17"]["role"] == "provisioned"
    # The active pointer points at the primary — the load-bearing invariant.
    assert _active(env) == "v16"


def test_source_migration_id_recorded_at_provision(env):
    _provision(env, "v16", "16")
    _provision(env, "v17", "17",
               data_path=str(env["tmp_path"] / "data" / "grafana-v17"),
               source_migration_id="2026-06-15-postgresql-16-to-17")
    v17 = next(t for t in _tracks(env) if t["tag"] == "v17")
    assert v17["source_migration_id"] == "2026-06-15-postgresql-16-to-17"


# --------------------------------------------------------------------------- #
# one-primary invariant                                                        #
# --------------------------------------------------------------------------- #

def test_promote_keeps_exactly_one_primary_and_demotes_prior(env):
    _provision(env, "v16", "16")
    _provision(env, "v17", "17",
               data_path=str(env["tmp_path"] / "data" / "grafana-v17"))

    res = lib.run_action(_common(env, action="promote_track", target_tag="v17"),
                         ctx={"port_probe": _port_up})
    assert res["changed"] is True
    assert res["result"]["previous_primary"] == "v16"
    assert res["result"]["new_primary"] == "v17"

    tracks = {t["tag"]: t for t in _tracks(env)}
    primaries = [tag for tag, t in tracks.items() if t.get("role") == "primary"]
    # EXACTLY one primary — the new one; the prior was demoted in the same write.
    assert primaries == ["v17"]
    # role='primary' ⟺ active=1 (the legacy routing pointer).
    assert _active(env) == "v17"
    assert tracks["v16"]["role"] == "secondary"
    assert tracks["v16"]["read_only"] is True
    assert "ttl_until" in tracks["v16"]
    assert tracks["v17"]["read_only"] is False
    assert "promoted_at" in tracks["v17"]


def test_promote_is_reversible_toggle(env):
    _provision(env, "v16", "16")
    _provision(env, "v17", "17",
               data_path=str(env["tmp_path"] / "data" / "grafana-v17"))
    lib.run_action(_common(env, action="promote_track", target_tag="v17"),
                   ctx={"port_probe": _port_up})
    # Re-promote the other → reverts.
    lib.run_action(_common(env, action="promote_track", target_tag="v16"),
                   ctx={"port_probe": _port_up})
    tracks = {t["tag"]: t for t in _tracks(env)}
    assert [tag for tag, t in tracks.items() if t.get("role") == "primary"] == ["v16"]
    assert _active(env) == "v16"


def test_promote_already_primary_is_noop(env):
    _provision(env, "v16", "16")
    res = lib.run_action(_common(env, action="promote_track", target_tag="v16"),
                         ctx={"port_probe": _port_up})
    assert res["changed"] is False
    assert res["result"]["noop"] is True


def test_promote_missing_target_fails(env):
    _provision(env, "v16", "16")
    res = lib.run_action(_common(env, action="promote_track", target_tag="ghost"),
                         ctx={"port_probe": _port_up})
    assert res.get("failed") is True
    assert "does not exist" in res["msg"]


def test_promote_deactivated_target_refused(env):
    _provision(env, "v16", "16")
    _provision(env, "v17", "17",
               data_path=str(env["tmp_path"] / "data" / "grafana-v17"))
    # Manually mark v17 deactivated, then attempt to promote it.
    state = _read_state(env)
    for t in state["coexistence"]["grafana"]["tracks"]:
        if t["tag"] == "v17":
            t["lifecycle"] = "deactivated"
            t["role"] = "deactivated"
    pathlib.Path(env["state_path"]).write_text(yaml.safe_dump(state))
    res = lib.run_action(_common(env, action="promote_track", target_tag="v17"),
                         ctx={"port_probe": _port_up})
    assert res.get("failed") is True
    assert "deactivated" in res["msg"]


def test_promote_down_target_refused_without_force(env):
    _provision(env, "v16", "16")
    _provision(env, "v17", "17",
               data_path=str(env["tmp_path"] / "data" / "grafana-v17"))
    # Health probe says the target port is down → refuse unless force.
    res = lib.run_action(_common(env, action="promote_track", target_tag="v17"),
                         ctx={"port_probe": _no_port})
    assert res.get("failed") is True
    assert "not answering" in res["msg"]
    # With force it goes through.
    res2 = lib.run_action(
        _common(env, action="promote_track", target_tag="v17", force=True),
        ctx={"port_probe": _no_port})
    assert res2["changed"] is True


# --------------------------------------------------------------------------- #
# deactivate-primary refusal (G-DEACTIVATE-NOT-PRIMARY / G-DEACTIVATE-LAST)     #
# --------------------------------------------------------------------------- #

def test_deactivate_primary_refused_without_force(env):
    _provision(env, "v16", "16")
    _provision(env, "v17", "17",
               data_path=str(env["tmp_path"] / "data" / "grafana-v17"))
    # v16 is primary (first provisioned). Deactivating it must refuse.
    res = lib.run_action(_common(env, action="deactivate_track", tag="v16"),
                         ctx={"port_probe": _port_up})
    assert res.get("failed") is True
    assert "primary" in res["msg"]


def test_deactivate_secondary_succeeds(env):
    _provision(env, "v16", "16")
    _provision(env, "v17", "17",
               data_path=str(env["tmp_path"] / "data" / "grafana-v17"))
    # v17 is the non-primary secondary → deactivates cleanly, data kept.
    res = lib.run_action(_common(env, action="deactivate_track", tag="v17"),
                         ctx={"port_probe": _port_up})
    assert res["changed"] is True
    assert res["result"]["role"] == "deactivated"
    assert res["result"]["compose_action"] == "stop"   # stop, NOT down
    tracks = {t["tag"]: t for t in _tracks(env)}
    assert tracks["v17"]["lifecycle"] == "deactivated"
    assert "deactivated_at" in tracks["v17"]
    # The primary is untouched and still primary (active pointer intact).
    assert _active(env) == "v16"
    assert tracks["v16"]["role"] == "primary"


def test_deactivate_last_live_track_refused(env):
    _provision(env, "v16", "16")
    # Only one live track → refuse (nothing to fall back to).
    res = lib.run_action(_common(env, action="deactivate_track", tag="v16"),
                         ctx={"port_probe": _port_up})
    assert res.get("failed") is True
    assert "only live track" in res["msg"]


def test_deactivate_primary_with_force_fails_over(env):
    _provision(env, "v16", "16")
    _provision(env, "v17", "17",
               data_path=str(env["tmp_path"] / "data" / "grafana-v17"))
    # Force-deactivate the primary v16 → fails over to v17, single primary holds.
    res = lib.run_action(
        _common(env, action="deactivate_track", tag="v16", force=True),
        ctx={"port_probe": _port_up})
    assert res["changed"] is True
    tracks = {t["tag"]: t for t in _tracks(env)}
    assert tracks["v16"]["role"] == "deactivated"
    assert tracks["v17"]["role"] == "primary"
    assert _active(env) == "v17"
    primaries = [tag for tag, t in tracks.items() if t.get("role") == "primary"]
    assert primaries == ["v17"]


def test_deactivate_missing_track_fails(env):
    _provision(env, "v16", "16")
    _provision(env, "v17", "17",
               data_path=str(env["tmp_path"] / "data" / "grafana-v17"))
    res = lib.run_action(_common(env, action="deactivate_track", tag="ghost"),
                         ctx={"port_probe": _port_up})
    assert res.get("failed") is True
    assert "does not exist" in res["msg"]


# --------------------------------------------------------------------------- #
# cancel-only-planned — bin/planned-coexistence.php --cancel                    #
# --------------------------------------------------------------------------- #

_PHP = shutil.which("php")
_CLI = _REPO / "files" / "anatomy" / "wing" / "bin" / "planned-coexistence.php"


def _make_wing_db(data_dir: pathlib.Path, status: str) -> None:
    """Seed a synthetic wing.db with a single coexistence_planned row carrying
    the given status + the B1 cancel columns."""
    data_dir.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(data_dir / "wing.db"))
    db.execute(
        """
        CREATE TABLE coexistence_planned (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            service TEXT NOT NULL,
            tag TEXT NOT NULL,
            target_version TEXT,
            port_offset INTEGER DEFAULT 10,
            status TEXT NOT NULL DEFAULT 'planned',
            applied_at TEXT,
            cancelled_at TEXT,
            cancelled_by TEXT,
            UNIQUE (service, tag, status)
        )
        """
    )
    db.execute(
        "INSERT INTO coexistence_planned (service, tag, target_version, status) "
        "VALUES ('postgresql', 'v17', '17', ?)",
        (status,),
    )
    db.commit()
    db.close()


def _run_cancel(data_dir: pathlib.Path, service="postgresql", tag="v17"):
    return subprocess.run(
        [_PHP, str(_CLI), "--cancel", f"--service={service}", f"--tag={tag}",
         f"--data-dir={data_dir}"],
        capture_output=True, text=True,
    )


@pytest.mark.skipif(_PHP is None, reason="php not installed")
def test_cancel_flips_planned_to_cancelled(tmp_path):
    data_dir = tmp_path / "wing" / "app" / "data"
    _make_wing_db(data_dir, "planned")
    proc = _run_cancel(data_dir)
    assert proc.returncode == 0, proc.stderr
    db = sqlite3.connect(str(data_dir / "wing.db"))
    row = db.execute(
        "SELECT status, cancelled_at FROM coexistence_planned "
        "WHERE service='postgresql' AND tag='v17'"
    ).fetchone()
    db.close()
    assert row[0] == "cancelled"
    assert row[1] is not None  # cancelled_at stamped


@pytest.mark.skipif(_PHP is None, reason="php not installed")
def test_cancel_refuses_when_no_planned_row(tmp_path):
    # The row is already applied → cancel must refuse (exit 1), no host state to
    # dequeue: an applied track goes deactivate → cleanup, not cancel.
    data_dir = tmp_path / "wing" / "app" / "data"
    _make_wing_db(data_dir, "applied")
    proc = _run_cancel(data_dir)
    assert proc.returncode == 1
    assert "no status=planned row" in proc.stderr
    # The applied row is untouched.
    db = sqlite3.connect(str(data_dir / "wing.db"))
    status = db.execute(
        "SELECT status FROM coexistence_planned "
        "WHERE service='postgresql' AND tag='v17'"
    ).fetchone()[0]
    db.close()
    assert status == "applied"


@pytest.mark.skipif(_PHP is None, reason="php not installed")
def test_cancel_requires_service_and_tag(tmp_path):
    data_dir = tmp_path / "wing" / "app" / "data"
    _make_wing_db(data_dir, "planned")
    proc = subprocess.run(
        [_PHP, str(_CLI), "--cancel", f"--data-dir={data_dir}"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 2
    assert "requires --service and --tag" in proc.stderr
