"""Gate (backup ↔ restore joint): one declared postgres db comes back alone.

2026-10-25: the dumpall held Paperclip whole, but restore replayed all of it or
nothing, Authentik included, so a blank that cleans Authentik could not keep
Paperclip. Now every `backup_postgres_dbs` entry gets its own pg_dump beside the
dumpall and `restore_postgres_dbs=<db>` replaces only that database.

Offline half (every commit): the REAL rendered backup wrapper stages
postgres-paperclip.sql.gz, and restore plans it alone, dry run by default.
Live half (NOS_LIVE=1, scratch containers only): that wrapper dumps a two-db
instance, the REAL tasks/restore.yml puts paperclip into a fresh instance whose
other db differs, and the other db stays as it was.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
import yaml

from test_backup_without_rustfs_goes_to_restic import execute, render

REPO = Path(__file__).resolve().parents[2]
IMAGE = "postgres:16.15-alpine"
DOCKER = "docker"  # resolved in the live fixture: the offline boundary shims it until then
DOCKER_CONFIG = os.environ.get("DOCKER_CONFIG", str(Path.home() / ".docker"))  # HOME moves to tmp below
PG_DECL = [{"db": "paperclip", "verify": ["companies", "projects", "issues"]}]


def _restore(tmp_path: Path, staged: Path, container: str, confirm: bool, app: str, path: str = "", check: bool = False) -> str:
    play = [{"hosts": "localhost", "connection": "local", "gather_facts": True,
             "gather_subset": ["!all", "min"],
             "vars": {"ansible_python_interpreter": sys.executable, "restore_date": "2026-10-29",
                      "restore_from": str(staged.parent), "restore_postgres_dbs": "paperclip",
                      "restore_confirm": confirm, "postgresql_container_name": container,
                      "backup_postgres_dbs": [{**PG_DECL[0], "containers": [app]}],
                      "nos_data_root": str(tmp_path / "nos"), "backup_alpine_image": "alpine:3",
                      "rustfs_access_key": "x", "rustfs_secret_key": "y"},
             "tasks": [{"import_tasks": str(REPO / "tasks/restore.yml")}]}]
    (tmp_path / "restore.yml").write_text(yaml.safe_dump(play))
    env = {**os.environ, "HOME": str(tmp_path), "ANSIBLE_LOCAL_TEMP": str(tmp_path / ".ansible"),
           "DOCKER_CONFIG": DOCKER_CONFIG, "PATH": path + os.environ["PATH"]}
    r = subprocess.run([sys.executable, "-m", "ansible.cli.playbook", "-i", "localhost,", str(tmp_path / "restore.yml")] + ["--check"] * check,
                       capture_output=True, text=True, env=env, cwd=tmp_path, timeout=600)
    (tmp_path / f"restore-{confirm}.log").write_text(r.stdout + r.stderr)
    assert r.returncode == 0, (r.stdout + r.stderr)[-4000:]
    return r.stdout


def test_the_backup_stages_a_paperclip_dump_and_restore_plans_it_alone(tmp_path):
    script = render(tmp_path, "profiles/core.yml", {"install_paperclip": True})
    execute(tmp_path, script)
    staged = tmp_path / "backups/staging/postgres-paperclip.sql.gz"
    assert staged.is_file(), "backup_postgres_dbs declares paperclip but the backup staged no per-db dump"
    assert "pg_dump -U postgres -d paperclip" in (tmp_path / "docker.calls").read_text()
    (staged.parent / "postgres.sql.gz").write_bytes(b"")  # the dumpall sits beside it
    calls = tmp_path / "docker.calls"
    calls.write_text("")
    out = _restore(tmp_path, staged, "infra-postgresql-1", False, "devops-paperclip-1", f"{tmp_path}/stub/bin:",
                   check=True)  # confirm=False: the plan alone; --check: the operator's preview
    assert "Files:     postgres-paperclip.sql.gz\\n" in out, out[-3000:]
    assert "DRY RUN" in out and "stop:     devops-paperclip-1" in out, out[-3000:]
    assert calls.read_text() == "", f"a dry run reached for docker: {calls.read_text()}"


def _pg(name: str, *sql: str, db: str = "postgres") -> str:
    out = ""
    for q in sql:
        out = subprocess.run([DOCKER, "exec", name, "psql", "-U", "postgres", "-d", db, "-v", "ON_ERROR_STOP=1",
                              "-Atqc", q], capture_output=True, text=True, check=True).stdout.strip()
    return out


def _start(name: str) -> None:
    subprocess.run([DOCKER, "run", "-d", "--rm", "--name", name, "-e", "POSTGRES_HOST_AUTH_METHOD=trust",
                    IMAGE], capture_output=True, check=True)
    for _ in range(60):
        if subprocess.run([DOCKER, "exec", name, "pg_isready", "-U", "postgres"], capture_output=True).returncode == 0 \
           and subprocess.run([DOCKER, "exec", name, "psql", "-U", "postgres", "-Atqc", "select 1"],
                              capture_output=True).returncode == 0:
            return
        subprocess.run(["sleep", "1"])
    raise RuntimeError(f"{name} never became ready")


def _seed(name: str, authentik_row: str, companies: list[str]) -> None:
    _pg(name, "create role paperclip login", "create database paperclip owner paperclip", "create database authentik")
    _pg(name, "create table marker(v text)", f"insert into marker values ('{authentik_row}')", db="authentik")
    _pg(name, "set role paperclip",
        "create table companies(id serial primary key, name text)",
        "create table projects(id serial primary key, name text)",
        "create table issues(id serial primary key, body text)",
        *[f"insert into companies(name) values ('{c}')" for c in companies], db="paperclip")


@pytest.fixture
def two_instances():
    global DOCKER
    DOCKER = shutil.which("docker") or "docker"
    if subprocess.run([DOCKER, "image", "inspect", IMAGE], capture_output=True).returncode != 0:
        pytest.skip(f"docker with {IMAGE} not available")
    tag = uuid.uuid4().hex[:8]
    old, new = f"nos-test-pgdb-old-{tag}", f"nos-test-pgdb-new-{tag}"
    try:
        _start(old)
        _start(new)
        yield old, new
    finally:
        subprocess.run([DOCKER, "rm", "-f", old, new], capture_output=True)


@pytest.mark.live
def test_paperclip_comes_back_and_authentik_stays(two_instances, tmp_path):
    old, new = two_instances
    _seed(old, "authentik-before-blank", ["Acme", "multi\nline\tname"])
    _pg(old, "set role paperclip", "insert into issues(body) values ('first')", db="paperclip")
    _seed(new, "authentik-after-blank", [])  # the blank + converge: fresh Authentik, empty Paperclip

    # docker reaches ONLY the scratch containers; any other call (an estate container) is a stub.
    def forward_only(to: str) -> None:
        (tmp_path / "stub/bin/docker").write_text(
            f'#!/bin/bash\nexport DOCKER_CONFIG="{DOCKER_CONFIG}"\n'
            f'case "$*" in *{to}*) exec "{DOCKER}" "$@";; esac\necho "-- stub: $*"\n')

    # 1. backup: the real wrapper.
    script = render(tmp_path, "profiles/core.yml", {"install_paperclip": True, "postgresql_container_name": old})
    forward_only(old)
    execute(tmp_path, script)
    staged = tmp_path / "backups/staging/postgres-paperclip.sql.gz"
    assert staged.is_file(), "the backup wrote no per-db dump for paperclip: " + \
        (tmp_path / "backups/backup.log").read_text()[-2000:]

    # 2. restore: dry run changes nothing, confirm replaces paperclip only.
    app, stub = f"{new}-app-absent", f"{tmp_path}/stub/bin:"
    forward_only(new)
    _restore(tmp_path, staged, new, False, app, stub)
    assert _pg(new, "select count(*) from companies", db="paperclip") == "0", "the dry run wrote"
    _restore(tmp_path, staged, new, True, app, stub)
    assert _pg(new, "select string_agg(name, '|' order by id) from companies", db="paperclip") == "Acme|multi\nline\tname"
    assert _pg(new, "select body from issues", db="paperclip") == "first"
    assert _pg(new, "select pg_get_userbyid(datdba) from pg_database where datname='paperclip'") == "paperclip"
    assert _pg(new, "select v from marker", db="authentik") == "authentik-after-blank", "restore touched another db"
    assert _pg(new, "select 1 from pg_database where datname='paperclip_pre_restore_20261029'") == "1", \
        "the replaced db was not kept as a snapshot"
