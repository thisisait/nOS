"""One journey through the backup role's paths that run a real ansible-playbook: the
main.yml preflight that refuses a backup with no repo, tasks/restore.yml replaying a set
from a local directory, and the weekly drill that proves each per-db pg_dump replays.
Nightly lane (tests/_lanes.yml), as each of its source files was.

Absorbed (2026-11-08, roadmap gate-diet-role-journeys), one section each:
  test_backup_preflight_refuses_empty_repo, test_restore_from_a_local_dir,
  test_the_drill_replays_every_postgres_db.
Every assert of those files survives here with the same inputs and expectations.
"""

from __future__ import annotations

import gzip
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import nos_identity as ni  # noqa: E402

RESTORE = REPO / "tasks/restore.yml"
BACKUP_YML = REPO / "tasks/backup.yml"


# ── test_backup_preflight_refuses_empty_repo ────────────────────────────────
# Client host 2026-10-16: configure_backup with an empty restic_repo failed in
# tasks/backup.yml after ~680 tasks. The main.yml preflight refuses it in
# seconds (Backrest seeds from restic_repo too); runs the real task through
# Ansible, and the rule lives in one place.

NAME = "[Preflight] Refuse a backup without a restic_repo"
needs_ansible = pytest.mark.skipif(importlib.util.find_spec("ansible") is None, reason="runs the task through real Ansible")


def _preflight_task() -> dict | None:
    play = yaml.safe_load((REPO / "main.yml").read_text())[0]
    return next((t for t in play["pre_tasks"] if t.get("name") == NAME), None)


@needs_ansible
@pytest.mark.parametrize("extra, refused", [
    ({"configure_backup": True, "restic_repo": ""}, True),
    ({"configure_backup": True}, True),
    ({"configure_backup": True, "restic_repo": "/Volumes/Backup/restic"}, False),
    ({"configure_backup": False, "restic_repo": ""}, False),
    ({"configure_backup": True, "restic_repo": "", "install_backrest": True}, True),
    ({"install_backrest": True, "restic_repo": ""}, True),
    ({"install_backrest": True, "restic_repo": "/Volumes/Backup/restic"}, False),
])
def test_the_preflight_refuses_backup_without_a_repo(tmp_path, extra, refused):
    task = _preflight_task()
    assert task, f"main.yml pre_tasks has no '{NAME}'"
    play = [{"hosts": "localhost", "connection": "local", "gather_facts": False,
             "vars": {"ansible_python_interpreter": sys.executable, **extra}, "tasks": [task]}]
    (tmp_path / "play.yml").write_text(yaml.safe_dump(play))
    r = subprocess.run([sys.executable, "-m", "ansible.cli.playbook", "-i", "localhost,", str(tmp_path / "play.yml")],
                       capture_output=True, text=True, cwd=tmp_path, timeout=120,
                       env={**os.environ, "ANSIBLE_LOCAL_TEMP": str(tmp_path / ".ansible")})
    assert (r.returncode != 0) is refused, r.stdout[-2000:]
    if refused:
        assert "restic_repo is empty" in r.stdout and "config.yml" in r.stdout


def test_the_rule_lives_in_one_place():
    late = [t.get("name") for t in yaml.safe_load(BACKUP_YML.read_text())
            if "restic_repo is empty" in str((t.get("ansible.builtin.fail") or {}).get("msg"))]
    assert not late, f"tasks/backup.yml re-checks restic_repo; the preflight owns it: {late}"


# ── test_restore_from_a_local_dir ───────────────────────────────────────────
# After the 2026-10-09 blank (`--remove=data` wipes RustFS too) the only copy was
# ~/backups/staging and restore.yml read only s3://. `restore_from` replays a
# local set; the old WAL must not outlive its database (KEAP crash-looped on
# SQLITE_CORRUPT 10-10) and the Iris ledger is rebuilt from its dump.

needs_ansible = pytest.mark.skipif(shutil.which("ansible-playbook") is None
                                   and not os.path.exists(os.path.join(os.path.dirname(sys.executable), "ansible-playbook")),
                                   reason="ansible not installed")


@needs_ansible
def test_a_local_backup_set_is_planned_without_s3(tmp_path):
    src = tmp_path / "pre-remove"
    src.mkdir()
    with gzip.open(src / "keap-db.gz", "wb") as f:
        f.write(b"SQLite format 3\x00")
    (src / "mariadb.sql.gz").write_bytes(gzip.compress(b"-- dump"))
    stubs = tmp_path / "bin"
    stubs.mkdir()
    for name in ("docker", "aws"):
        p = stubs / name
        p.write_text(f'#!/bin/sh\necho "{name} $*" >> "{tmp_path}/calls.log"\nexit 1\n')
        p.chmod(0o755)
    play = [{"hosts": "localhost", "connection": "local", "gather_facts": True,
             "gather_subset": ["!all", "min"],
             "vars": {"ansible_python_interpreter": sys.executable,
                      "restore_date": "2026-10-09", "restore_from": str(src),
                      "restore_sources": "keap-db", "nos_data_root": str(tmp_path / "nos"),
                      "backup_alpine_image": "alpine:3", "rustfs_access_key": "x",
                      "rustfs_secret_key": "y"},
             "tasks": [{"import_tasks": str(RESTORE)}]}]
    (tmp_path / "play.yml").write_text(yaml.safe_dump(play))
    env = {**os.environ, "PATH": f"{stubs}:/usr/bin:/bin:/usr/sbin:/sbin",
           "ANSIBLE_LOCAL_TEMP": str(tmp_path / ".ansible"), "HOME": str(tmp_path)}
    r = subprocess.run([sys.executable, "-m", "ansible.cli.playbook", "-i", "localhost,", "--check",
                        str(tmp_path / "play.yml")], capture_output=True, text=True, env=env,
                       cwd=tmp_path, timeout=300)
    out = r.stdout + r.stderr
    assert "Files:     keap-db.gz" in out, out[-3000:]
    calls = (tmp_path / "calls.log").read_text() if (tmp_path / "calls.log").exists() else ""
    assert "aws" not in calls, f"a local restore reached for S3:\n{calls}"


@needs_ansible
def test_the_old_wal_does_not_outlive_its_database(tmp_path):
    # 2026-10-10: the snapshot moved keap.db aside but left keap.db-wal; KEAP replayed
    # the old WAL into the restored file and crash-looped on SQLITE_CORRUPT.
    src = tmp_path / "set"
    src.mkdir()
    with gzip.open(src / "keap-db.gz", "wb") as f:
        f.write(b"restored")
    data = tmp_path / "keap"
    data.mkdir()
    for suffix, body in (("", b"old"), ("-wal", b"old-wal"), ("-shm", b"old-shm")):
        (data / f"keap.db{suffix}").write_bytes(body)
    stubs = tmp_path / "bin"
    stubs.mkdir()
    for name in ("docker", "aws"):
        p = stubs / name
        p.write_text("#!/bin/sh\nexit 0\n")
        p.chmod(0o755)
    play = [{"hosts": "localhost", "connection": "local", "gather_facts": True,
             "gather_subset": ["!all", "min"],
             "vars": {"ansible_python_interpreter": sys.executable,
                      "restore_date": "2026-10-09", "restore_from": str(src),
                      "restore_sources": "keap-db", "keap_data_dir": str(data),
                      "nos_data_root": str(tmp_path / "nos"), "backup_alpine_image": "alpine:3",
                      "rustfs_access_key": "x", "rustfs_secret_key": "y"},
             "tasks": [{"import_tasks": str(RESTORE)}]}]
    (tmp_path / "play.yml").write_text(yaml.safe_dump(play))
    env = {**os.environ, "PATH": f"{stubs}:/usr/bin:/bin:/usr/sbin:/sbin",
           "ANSIBLE_LOCAL_TEMP": str(tmp_path / ".ansible"), "HOME": str(tmp_path)}
    r = subprocess.run([sys.executable, "-m", "ansible.cli.playbook", "-i", "localhost,",
                        str(tmp_path / "play.yml")], capture_output=True, text=True, env=env,
                       cwd=tmp_path, timeout=300, stdin=subprocess.DEVNULL)
    out = r.stdout + r.stderr
    assert (data / "keap.db").read_bytes() == b"restored", out[-3000:]
    assert not (data / "keap.db-wal").exists(), "the old WAL sits beside the restored DB"
    assert not (data / "keap.db-shm").exists(), "the old SHM sits beside the restored DB"
    snap = data / "keap.db.pre-restore-2026-10-09"
    assert (Path(f"{snap}-wal")).read_bytes() == b"old-wal", "the snapshot lost its WAL"


@needs_ansible
def test_the_iris_ledger_is_rebuilt_from_its_dump(tmp_path):
    # 2026-10-25: ledger.db had no backup, so a blank lost Iris's history. WAL mode, like keap.db.
    import sqlite3
    src = tmp_path / "set"
    src.mkdir()
    db = sqlite3.connect(tmp_path / "orig.db")
    db.executescript("create table events(x); insert into events values ('turn');")
    (src / "thalamus-ledger.sql.gz").write_bytes(gzip.compress("\n".join(db.iterdump()).encode()))
    data = tmp_path / "thalamus"
    data.mkdir()
    for suffix, body in (("", b"old"), ("-wal", b"old-wal"), ("-shm", b"old-shm")):
        (data / f"ledger.db{suffix}").write_bytes(body)
    stubs = tmp_path / "bin"
    stubs.mkdir()
    for name in ("docker", "aws", "launchctl", "systemctl"):
        p = stubs / name
        p.write_text(f'#!/bin/sh\necho "{name} $*" >> "{tmp_path}/calls.log"\nexit 0\n')
        p.chmod(0o755)
    # A fake label too: even a real launchctl must never reach the running Iris.
    play = [{"hosts": "localhost", "connection": "local", "gather_facts": True,
             "gather_subset": ["!all", "min"],
             "vars": {"ansible_python_interpreter": sys.executable,
                      "restore_date": "2026-10-25", "restore_from": str(src),
                      "restore_sources": "thalamus-ledger", "thalamus_data_dir": str(data),
                      "thalamus_launchd_label": "eu.thisisait.nos.test-thalamus",
                      "nos_data_root": str(tmp_path / "nos"), "backup_alpine_image": "alpine:3",
                      "rustfs_access_key": "x", "rustfs_secret_key": "y"},
             "tasks": [{"import_tasks": str(RESTORE)}]}]
    (tmp_path / "play.yml").write_text(yaml.safe_dump(play))
    env = {**os.environ, "PATH": f"{stubs}:/usr/bin:/bin:/usr/sbin:/sbin",
           "ANSIBLE_LOCAL_TEMP": str(tmp_path / ".ansible"), "HOME": str(tmp_path)}
    r = subprocess.run([sys.executable, "-m", "ansible.cli.playbook", "-i", "localhost,",
                        str(tmp_path / "play.yml")], capture_output=True, text=True, env=env,
                       cwd=tmp_path, timeout=300, stdin=subprocess.DEVNULL)
    out = r.stdout + r.stderr
    assert r.returncode == 0, out[-3000:]
    assert sqlite3.connect(data / "ledger.db").execute("select x from events").fetchall() == [("turn",)]
    assert not (data / "ledger.db-wal").exists(), "the old WAL sits beside the restored ledger"
    assert (data / "ledger.db.pre-restore-2026-10-25-wal").read_bytes() == b"old-wal"
    calls = (tmp_path / "calls.log").read_text()
    assert "bootout" in calls and "bootstrap" in calls and "test-thalamus" in calls, calls


# ── test_the_drill_replays_every_postgres_db ────────────────────────────────
# 2026-10-31: Paperclip got its own pg_dump and its in-place restore needed an
# owner realign, yet the weekly drill opened only three SQLite stores. Offline:
# the real templar renders backup-verify.sh and its main() runs with aws/docker
# stubbed; live (NOS_LIVE=1, drill-test-* only): a real dump replays and counts.

VERIFY = REPO / "roles/pazny.backup/files/backup-verify.sh"
IMAGE = "postgres:16.15-alpine"
KEY = "drill-test-key"
DATE = "2026-10-31"
DECLARED = ni.resolve_list("backup_postgres_dbs", ni.default_layers())   # the committed layers, not config.yml

# aws: `s3 ls` lists one dated prefix, `s3 cp` copies from $BUCKET (a local dir) or fails.
STUB_AWS = """#!/bin/bash
echo "$*" >> "$HOME/aws.calls"
[[ "$*" == *" s3 ls "* ]] && { echo "                           PRE %s/"; exit 0; }
src="$(printf '%%s\\n' "$@" | grep '^s3://')"; dst="${@: -1}"
[[ -f "$BUCKET/${src#s3://*/}" ]] && cp "$BUCKET/${src#s3://*/}" "$dst"
""" % DATE


def render(tmp: Path, extra: dict) -> Path:
    out = tmp / "backup-verify.sh"
    play = [{"hosts": "localhost", "connection": "local", "gather_facts": True, "gather_subset": ["!all", "min"],
             "vars_files": [str(REPO / "roles/pazny.backup/defaults/main.yml"), str(REPO / "default.credentials.yml")]
             + [str(p) for p in ni.default_layers()],
             "tasks": [{"ansible.builtin.template": {"src": str(VERIFY), "dest": str(out), "mode": "0700"}}]}]
    (tmp / "play.yml").write_text(yaml.safe_dump(play, sort_keys=False))
    ev = {"global_password_prefix": "x", "rustfs_access_key": "x", "rustfs_secret_key": "y", "bone_secret": "",
          "backup_notify_enabled": False, "backup_encryption_enabled": True, "backup_encryption_passphrase": KEY,
          "backup_encryption_keys_previous": [], "backup_databases_postgresql": True,
          "backup_target_endpoint": "http://drill-test.invalid", "install_postgis": False,
          "backup_verify_log": str(tmp / "verify.log"), "backup_verify_result": str(tmp / "verify.json"),
          **{d["flag"]: True for d in DECLARED}, **extra}
    (tmp / "ev.json").write_text(json.dumps(ev))
    (tmp / "ansible.cfg").write_text("[defaults]\n")
    env = {**os.environ, "HOME": str(tmp), "ANSIBLE_CONFIG": str(tmp / "ansible.cfg"),
           "ANSIBLE_LOCALHOST_WARNING": "false", "ANSIBLE_INVENTORY_UNPARSED_WARNING": "false"}
    r = subprocess.run([sys.executable, "-m", "ansible.cli.playbook", "-i", "localhost,", str(tmp / "play.yml"),
                        "-e", f"@{tmp / 'ev.json'}"], cwd=tmp, env=env, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-2000:]
    return out


def drill(tmp: Path, script: Path, docker: str) -> dict:
    """Run the rendered drill's main() with aws (and docker, per `docker`) stubbed on PATH."""
    stub = tmp / "stub"
    stub.mkdir(exist_ok=True)
    for name, body in (("aws", STUB_AWS), ("docker", docker)):
        (stub / name).write_text(body)
        (stub / name).chmod(0o755)
    (tmp / "bucket").mkdir(exist_ok=True)
    env = {"HOME": str(tmp), "PATH": f"{stub}:{os.environ['PATH']}", "BUCKET": str(tmp / "bucket")}
    r = subprocess.run(["/bin/bash", str(script), DATE], env=env, cwd=tmp, capture_output=True, text=True, timeout=600)
    assert (tmp / "verify.json").is_file(), r.stdout + r.stderr + (tmp / "verify.log").read_text()
    return {a["name"]: a for a in json.loads((tmp / "verify.json").read_text())["artifacts"]}


def test_every_declared_db_is_drilled_and_none_touches_the_estate(tmp_path):
    script = render(tmp_path, {})
    rows = drill(tmp_path, script, '#!/bin/bash\necho "$*" >> "$HOME/docker.calls"\nexit 1\n')
    missing = [d["db"] for d in DECLARED if f"postgres-{d['db']}" not in rows]
    assert not missing, f"backup_postgres_dbs declares {missing} but the drill never tried them: {sorted(rows)}"
    text = script.read_text()
    assert "infra-" not in text and "devops-" not in text, "the drill names an estate container"
    runs = [ln for ln in text.splitlines() if "docker run" in ln]
    assert runs and not [ln for ln in runs if " -p " in ln or "--publish" in ln], runs


def _psql(ctr: str, sql: str, db: str = "postgres") -> str:
    return subprocess.run([shutil.which("docker"), "exec", ctr, "psql", "-U", "postgres", "-d", db,
                           "-v", "ON_ERROR_STOP=1", "-Atqc", sql], capture_output=True, text=True, check=True).stdout


@pytest.mark.live
def test_a_dump_owned_by_postgres_replays_into_a_scratch_postgres(tmp_path):
    docker = shutil.which("docker")
    if not docker or subprocess.run([docker, "image", "inspect", IMAGE], capture_output=True).returncode:
        pytest.skip(f"docker with {IMAGE} not available")
    db, src = "test-paperclip", f"drill-test-src-{uuid.uuid4().hex[:8]}"
    try:
        subprocess.run([docker, "run", "-d", "--rm", "--name", src, "-e", "POSTGRES_HOST_AUTH_METHOD=trust", IMAGE],
                       capture_output=True, check=True)
        for _ in range(60):
            if subprocess.run([docker, "exec", src, "psql", "-h", "127.0.0.1", "-U", "postgres", "-Atqc", "select 1"],
                              capture_output=True).returncode == 0:
                break
            subprocess.run(["sleep", "1"])
        _psql(src, f'create role "{db}" login')
        _psql(src, f'create database "{db}" owner "{db}"')
        _psql(src, f'set role "{db}"; create table companies(id serial primary key, name text);'
                   "create table projects(id serial primary key); create table issues(id serial primary key, body text);"
                   "insert into companies(name) values ('Acme'), (E'multi\\nline\\tname');"
                   "insert into issues(body) values ('first'); reset role; alter table issues owner to postgres", db=db)
        dump = subprocess.run([docker, "exec", src, "pg_dump", "-U", "postgres", "-d", db],
                              capture_output=True, check=True).stdout
        assert b"OWNER TO postgres" in dump, "precondition: the dump must carry a table owned by postgres"
        (tmp_path / "bucket" / DATE).mkdir(parents=True)
        plain = tmp_path / "plain.gz"
        plain.write_bytes(gzip.compress(dump))
        subprocess.run(["openssl", "enc", "-aes-256-cbc", "-md", "sha512", "-pbkdf2", "-iter", "100000", "-salt",
                        "-pass", f"pass:{KEY}", "-in", str(plain),
                        "-out", str(tmp_path / f"bucket/{DATE}/postgres-{db}.sql.gz.enc")], check=True)

        script = render(tmp_path, {"backup_postgres_dbs": [{"db": db, "flag": "install_paperclip",
                                                            "verify": ["companies", "projects", "issues"]}]})
        # docker reaches ONLY drill-test-* objects; anything else is recorded and refused.
        guard = (f'#!/bin/bash\necho "$*" | tr "\\n" " " >> "$HOME/docker.calls"; echo >> "$HOME/docker.calls"\n'
                 f'case "$*" in *drill-test-*) exec "{docker}" "$@";; esac\nexit 1\n')
        rows = drill(tmp_path, script, guard)
        row = rows[f"postgres-{db}"]
        assert row["success"], row["detail"] + "\n" + (tmp_path / "verify.log").read_text()[-3000:]
        assert row["rows"] == "companies=2 issues=1 projects=0" and isinstance(row["seconds"], int), row
        calls = (tmp_path / "docker.calls").read_text().splitlines()
        assert calls and all("drill-test-" in c for c in calls), calls
        left = subprocess.run([docker, "ps", "-aq", "--filter", f"name=drill-{db}-"], capture_output=True, text=True)
        assert left.stdout.strip() == "", "the drill left its scratch container behind"
    finally:
        subprocess.run([docker, "rm", "-f", src], capture_output=True)
