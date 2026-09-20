"""EspoCRM is not on infra MariaDB — nightly copy #1 must dump espocrm-db.

The shared mariadb-dump --all-databases never sees the apps-stack embedded
server. A named-volume tar of mysql datadir is not that dump.
"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BACKUP_SH = REPO / "roles" / "pazny.backup" / "files" / "backup.sh"
BACKUP_DEFAULTS = REPO / "roles" / "pazny.backup" / "defaults" / "main.yml"
MANIFEST = REPO / "apps" / "espocrm.yml"


def test_espocrm_dump_is_a_named_backup_source():
    src = BACKUP_SH.read_text(encoding="utf-8")
    assert "run_espocrm()" in src
    main = src.split("\nmain()", 1)[1]
    assert "run_espocrm" in main
    assert "espocrm.sql.gz" in src
    defaults = BACKUP_DEFAULTS.read_text(encoding="utf-8")
    block = defaults.split("backup_espocrm_volumes:", 1)[1].split("backup_dirs_to_dump:", 1)[0]
    assert "apps_espocrm_data" in block
    assert "apps_espocrm_db" not in block
    assert "container_name: espocrm-db" in MANIFEST.read_text(encoding="utf-8")
