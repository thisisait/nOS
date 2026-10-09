"""restore.yml replays a backup set from a local directory (`restore_from`).

`nos --remove=data` wipes RustFS with everything else, so after the blank of
2026-10-09 the only copy of the pre-removal dumps was ~/backups/staging — and
restore.yml read only s3://backups/<date>/, so the roadmap table's 659 rows of
status had no restore path the playbook owned.
"""
from __future__ import annotations

import gzip
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]

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
             "tasks": [{"import_tasks": str(REPO / "tasks/restore.yml")}]}]
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
