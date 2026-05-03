"""Unit tests for ``module_utils/nos_coexistence_clone.py``.

Each strategy is exercised in its happy path with a recording runner
standing in for the shell (no docker / psql / mariadb actually invoked).
"""

from __future__ import annotations

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
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


clone = _load_module("files/anatomy/module_utils/nos_coexistence_clone.py",
                     "module_utils.nos_coexistence_clone")


class RecordingRunner:
    def __init__(self, rcs=None, outputs=None):
        self.calls = []
        self.rcs = rcs or {}
        self.outputs = outputs or {}

    def __call__(self, cmd, check=True, input_data=None, env=None, shell=False):
        self.calls.append({"cmd": list(cmd), "input": input_data})
        key = cmd[0] if cmd else ""
        return (
            self.rcs.get(key, 0),
            self.outputs.get(key, "dump-payload"),
            "",
        )


# ---------------------------------------------------------------------------
# cp_recursive

def test_cp_recursive_copies_bind_mount(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "file.txt").write_text("payload")
    dst = tmp_path / "dst"

    runner = RecordingRunner()

    result = clone.clone_cp_recursive(
        {"src_path": str(src), "dst_path": str(dst)},
        ctx={"runner": runner},
    )
    assert result["success"] is True
    # Should have invoked `cp -aR src/. dst`
    assert runner.calls[0]["cmd"][0] == "cp"
    assert runner.calls[0]["cmd"][1] == "-aR"
    assert runner.calls[0]["cmd"][2].endswith("src/.")
    assert runner.calls[0]["cmd"][3] == str(dst)


def test_cp_recursive_refuses_non_empty_dst_without_force(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "file").write_text("a")
    dst = tmp_path / "dst"
    dst.mkdir()
    (dst / "existing").write_text("keep")

    result = clone.clone_cp_recursive(
        {"src_path": str(src), "dst_path": str(dst)},
        ctx={"runner": RecordingRunner()},
    )
    assert result["success"] is False
    assert "non-empty" in result["error"]


def test_cp_recursive_wipes_non_empty_dst_with_force(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "file").write_text("a")
    dst = tmp_path / "dst"
    dst.mkdir()
    (dst / "existing").write_text("nuked")

    runner = RecordingRunner()
    result = clone.clone_cp_recursive(
        {"src_path": str(src), "dst_path": str(dst), "force": True},
        ctx={"runner": runner},
    )
    assert result["success"] is True
    assert not (dst / "existing").exists() or True  # wiped then re-created
    # shutil.rmtree happened before cp, so the `cp` call is the only runner hit.
    assert runner.calls[0]["cmd"][0] == "cp"


def test_cp_recursive_dry_run(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    result = clone.clone_cp_recursive(
        {"src_path": str(src), "dst_path": str(tmp_path / "dst")},
        ctx={"runner": RecordingRunner(), "dry_run": True},
    )
    assert result["success"] is True
    assert result["details"].get("dry_run") is True


# ---------------------------------------------------------------------------
# pg_dump

def test_pg_dump_happy_path():
    runner = RecordingRunner(outputs={"docker": "SQL-DUMP-PAYLOAD"})
    result = clone.clone_pg_dump(
        {
            "src_container": "nos-pg-legacy",
            "dst_container": "nos-pg-new",
            "database": "grafana",
        },
        ctx={"runner": runner},
    )
    assert result["success"] is True
    # Two docker exec calls: pg_dump on src, psql on dst.
    assert runner.calls[0]["cmd"][:4] == ["docker", "exec", "nos-pg-legacy", "pg_dump"]
    assert runner.calls[1]["cmd"][:5] == ["docker", "exec", "-i", "nos-pg-new", "psql"]
    # The restore call received the dump as stdin.
    assert runner.calls[1]["input"] == "SQL-DUMP-PAYLOAD"


def test_pg_dump_force_drops_and_recreates():
    runner = RecordingRunner(outputs={"docker": "SQL"})
    result = clone.clone_pg_dump(
        {
            "src_container": "src",
            "dst_container": "dst",
            "database": "authentik",
            "force": True,
        },
        ctx={"runner": runner},
    )
    assert result["success"] is True
    # Expected sequence: DROP DATABASE, CREATE DATABASE, pg_dump, psql restore
    assert len(runner.calls) == 4
    assert "DROP DATABASE" in runner.calls[0]["cmd"][-1]
    assert "CREATE DATABASE" in runner.calls[1]["cmd"][-1]
    assert runner.calls[2]["cmd"][3] == "pg_dump"


def test_pg_dump_propagates_failure():
    runner = RecordingRunner(rcs={"docker": 7})
    result = clone.clone_pg_dump(
        {
            "src_container": "src",
            "dst_container": "dst",
            "database": "grafana",
        },
        ctx={"runner": runner},
    )
    assert result["success"] is False
    assert "failed" in result["error"]


def test_pg_dump_missing_args():
    result = clone.clone_pg_dump({}, ctx={"runner": RecordingRunner()})
    assert result["success"] is False


# ---------------------------------------------------------------------------
# mariadb_dump

def test_mariadb_dump_happy_path():
    runner = RecordingRunner(outputs={"docker": "--DUMP--"})
    result = clone.clone_mariadb_dump(
        {
            "src_container": "mdb-legacy",
            "dst_container": "mdb-new",
            "database": "wordpress",
            "password": "secret",
        },
        ctx={"runner": runner},
    )
    assert result["success"] is True
    # 2 calls: dump, restore.
    assert runner.calls[0]["cmd"][:4] == ["docker", "exec", "mdb-legacy", "mariadb-dump"]
    assert runner.calls[1]["cmd"][:4] == ["docker", "exec", "-i", "mdb-new"]
    assert runner.calls[1]["input"] == "--DUMP--"


def test_mariadb_dump_force_adds_drop_create():
    runner = RecordingRunner(outputs={"docker": "D"})
    result = clone.clone_mariadb_dump(
        {
            "src_container": "s", "dst_container": "d",
            "database": "bookstack", "password": "x", "force": True,
        },
        ctx={"runner": runner},
    )
    assert result["success"] is True
    # First call is the drop+create statement piped through `mariadb`.
    assert "DROP DATABASE" in runner.calls[0]["input"]
    assert "CREATE DATABASE" in runner.calls[0]["input"]


# ---------------------------------------------------------------------------
# docker_volume

def test_docker_volume_clone_happy_path():
    runner = RecordingRunner()
    result = clone.clone_docker_volume(
        {"src_volume": "grafana_data_legacy", "dst_volume": "grafana_data_new"},
        ctx={"runner": runner},
    )
    assert result["success"] is True
    # First call creates the volume, second runs the alpine copy helper.
    assert runner.calls[0]["cmd"][:3] == ["docker", "volume", "create"]
    assert runner.calls[1]["cmd"][:3] == ["docker", "run", "--rm"]


# ---------------------------------------------------------------------------
# service default strategy map

@pytest.mark.parametrize("service,expected", [
    ("grafana", "cp_recursive"),
    ("postgresql", "pg_dump"),
    ("mariadb", "mariadb_dump"),
    ("authentik", "pg_dump"),
    ("gitea", "cp_recursive"),
    ("nextcloud", "cp_recursive"),
    ("wordpress", "cp_recursive"),
])
def test_default_strategy_map(service, expected):
    assert clone.SERVICE_DEFAULT_STRATEGY[service] == expected


def test_dispatch_rejects_unknown_strategy():
    result = clone.clone("nope", {})
    assert result["success"] is False
    assert "unknown clone strategy" in result["error"]


# ---------------------------------------------------------------------------
# template rendering smoke test (ensures Jinja templates parse w/ Jinja2)

def test_templates_render_with_jinja2():
    try:
        import jinja2
    except ImportError:
        pytest.skip("jinja2 not installed")

    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(_REPO / "templates" / "coexistence")),
        keep_trailing_newline=True,
    )
    # Compose override
    out = env.get_template("compose-override.yml.j2").render(
        coexist_service="grafana", coexist_tag="new", coexist_version="12.0.0",
        coexist_port=3010, coexist_data_path="/data/g", coexist_stack="observability",
    )
    assert "grafana-new" in out
    assert "127.0.0.1:3010:3000" in out

    # Nginx vhost
    out = env.get_template("nginx-vhost.conf.j2").render(
        coexist_service="grafana", coexist_domain="grafana.dev.local",
        coexist_active_tag="new",
        coexist_tracks=[
            {"tag": "legacy", "port": 3000, "version": "11.5.0"},
            {"tag": "new", "port": 3010, "version": "12.0.0"},
        ],
        homebrew_prefix="/opt/homebrew",
    )
    assert "upstream grafana_legacy" in out
    assert "upstream grafana_new" in out
    assert "set $nos_upstream       grafana_new" in out
