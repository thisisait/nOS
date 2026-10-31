"""Gate (declaration ↔ drill joint): the weekly drill replays every per-db pg_dump.

2026-10-31: backup_postgres_dbs gave Paperclip its own dump, and the in-place
restore needed an owner realign before the app stopped restarting (74x). The
weekly drill opened only three SQLite stores, so nothing ever proved that a
postgres-<db>.sql.gz in the bucket replays at all.

Offline (every commit): the REAL templar renders backup-verify.sh with every
declared db switched on, and the REAL main() runs with aws/docker stubbed; the
result JSON must carry a postgres-<db> row per declaration, and the drill never
names an estate container or publishes a port.
Live (NOS_LIVE=1, drill-test-* containers only): a real pg_dump with a table
OWNER TO postgres goes through verify_postgres_db and comes back counted.
"""
from __future__ import annotations

import gzip
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

VERIFY = REPO / "roles/pazny.backup/files/backup-verify.sh"
IMAGE = "postgres:16.15-alpine"
KEY = "drill-test-key"
DATE = "2026-10-31"
DECLARED = yaml.safe_load((REPO / "default.config.yml").read_text(encoding="utf-8"))["backup_postgres_dbs"]

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
    db, src = "test-paperclip",f"drill-test-src-{uuid.uuid4().hex[:8]}"
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
