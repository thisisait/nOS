"""A good dump survives the backup that runs after a blank.

MEASURED 2026-10-31: a blank ran 10-30 17:47-18:25 and the Paperclip/Iris restore from
~/backups/staging was planned for after it. The 03:00 nightly ran first and overwrote the
staging files with the freshly reinstalled empty data: postgres-paperclip.sql.gz 6.2 MB ->
80 KB, dir-paperclip.tar.gz 726 MB -> 4.3 MB, thalamus-ledger.sql.gz 1.1 MB -> 361 B. The good
copies survived only in the pre-wipe restic snapshot. Two layers, both executed here:
  1. the pre-wipe step copies staging to backup_pre_blank_dir/<UTC stamp>, newest 2 kept;
  2. promoting a dump under a tenth of the one it replaces keeps the old one as <name>.prev
     and the status JSON says "shrank" (red-status reads it).
docker and restic are stubbed to fail: nothing here may reach a live estate.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import textwrap
from pathlib import Path

import jinja2
import yaml

REPO = Path(__file__).resolve().parents[2]
BACKUP = REPO / "roles/pazny.backup/files/backup.sh"
BACKUP_YML = REPO / "tasks/backup.yml"
PREWIPE = REPO / "tasks/pre-wipe-backup.yml"


def _stub_env(tmp: Path) -> dict:
    bin_ = tmp / "stubbin"
    bin_.mkdir(exist_ok=True)
    for tool in ("docker", "restic", "aws"):
        (bin_ / tool).write_text("#!/bin/sh\necho \"stub $0 refused\" >&2\nexit 97\n")
        (bin_ / tool).chmod(0o755)
    return dict(os.environ, PATH=f"{bin_}:{os.environ['PATH']}")


def _rendered(tmp: Path) -> str:
    env = jinja2.Environment(undefined=jinja2.Undefined, keep_trailing_newline=True)
    env.filters["bool"] = lambda v: str(v).lower() in ("1", "true", "yes")
    text = env.from_string(BACKUP.read_text(encoding="utf-8")).render(
        backup_staging_dir=str(tmp / "staging"), backup_status_file=str(tmp / "status.json"),
        backup_log_file=str(tmp / "backup.log"), backup_encryption_enabled=False,
        backup_overwrite_same_day=True, backup_dirs_to_dump=[],
        backup_retention_daily=7, backup_retention_weekly=4, backup_retention_monthly=6)
    return text.rsplit('\nmain "$@"', 1)[0]


def test_a_shrunk_dump_keeps_its_predecessor(tmp_path):
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "postgres-paperclip.sql.gz").write_bytes(b"g" * 1_048_576)
    (staging / "postgres-paperclip.sql.gz.part").write_bytes(b"e" * 1024)
    r = subprocess.run(["bash", "-c", _rendered(tmp_path) + "\nstatus_append postgres-paperclip 1024 1 1\n"
                        "status_append postgres-paperclip 0 1 0\n"],
                       capture_output=True, text=True, env=_stub_env(tmp_path), timeout=60)
    assert r.returncode == 0, r.stderr
    prev = staging / "postgres-paperclip.sql.gz.prev"
    assert prev.is_file() and prev.stat().st_size == 1_048_576, "the good dump was overwritten"
    first = json.loads((tmp_path / "status.json").read_text())["sources"][0]
    assert first["shrank"] == "from 1048576 to 1024", first
    assert prev.is_file(), "a later failed run removed the kept predecessor"


def test_a_small_or_growing_dump_is_just_promoted(tmp_path):
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "wing-db.sql.gz").write_bytes(b"o" * 4096)  # under the floor: no .prev
    (staging / "wing-db.sql.gz.part").write_bytes(b"n" * 10)
    r = subprocess.run(["bash", "-c", _rendered(tmp_path) + "\nstatus_append wing-db 10 1 1\n"],
                       capture_output=True, text=True, env=_stub_env(tmp_path), timeout=60)
    assert r.returncode == 0, r.stderr
    assert not (staging / "wing-db.sql.gz.prev").exists()
    assert (staging / "wing-db.sql.gz").read_bytes() == b"n" * 10
    assert "shrank" not in json.loads((tmp_path / "status.json").read_text())["sources"][0]


def _fn(src: str, name: str) -> str:
    m = re.search(rf"^( *){name}\(\) \{{\n.*?^\1\}}\n", src, re.S | re.M)
    assert m, f"{name} moved"
    return textwrap.dedent(m.group(0))


def test_the_direct_restic_path_uses_the_same_guard():
    assert _fn(BACKUP_YML.read_text(encoding="utf-8"), "keep_if_shrunk") == _fn(
        BACKUP.read_text(encoding="utf-8"), "keep_if_shrunk"), "the no-RustFS staging path lost the guard"


def _prewipe_copy_task() -> dict:
    for t in yaml.safe_load(PREWIPE.read_text(encoding="utf-8")):
        if "pre-blank" in t.get("name", "") and "ansible.builtin.shell" in t:
            return t
    raise AssertionError("pre-wipe-backup.yml has no step that keeps a pre-blank copy of staging")


def test_the_blank_keeps_its_own_copy_newest_two(tmp_path):
    task = _prewipe_copy_task()
    env_keys = task.get("environment") or {}
    assert "backup_staging_dir" in env_keys["NOS_STAGING"] and "backup_pre_blank_dir" in env_keys["NOS_PRE_BLANK"]
    src = tmp_path / "staging"
    (src / "keap-tables").mkdir(parents=True)
    (src / "postgres-paperclip.sql.gz").write_bytes(b"g" * 2048)
    (src / "keap-tables" / "manifest.json").write_text("{}")
    root = tmp_path / "pre-blank"
    env = _stub_env(tmp_path)
    for stamp in ("20261029T100000Z", "20261030T174700Z", "20261031T090000Z"):
        r = subprocess.run(["bash", "-c", task["ansible.builtin.shell"]], capture_output=True, text=True,
                           env=dict(env, NOS_STAGING=str(src), NOS_PRE_BLANK=str(root), NOS_STAMP=stamp),
                           timeout=60)
        assert r.returncode == 0, r.stderr
    assert sorted(p.name for p in root.iterdir()) == ["20261030T174700Z", "20261031T090000Z"]
    kept = root / "20261031T090000Z"
    assert (kept / "postgres-paperclip.sql.gz").read_bytes() == b"g" * 2048
    assert (kept / "keap-tables" / "manifest.json").is_file()
    # A later overwrite of staging (mv over the name, as backup.sh promotes) leaves the copy.
    (src / "new.part").write_bytes(b"e")
    os.replace(src / "new.part", src / "postgres-paperclip.sql.gz")
    assert (kept / "postgres-paperclip.sql.gz").stat().st_size == 2048


def test_the_blank_record_names_the_copy():
    main = (REPO / "main.yml").read_text(encoding="utf-8")
    line = re.search(r"\[Blank\] Append the open record.*?line: (.*?)\n\s+create:", main, re.S)
    assert line and "'pre_blank'" in line.group(1), "blank-runs.jsonl does not say where the pre-blank copy is"
