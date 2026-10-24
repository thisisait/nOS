"""A converge that crosses a one-way migration keeps a cold, verified copy first.

2026-10-24: Jellyfin 10.11 -> 12 rewrites its database (rollback = full restore)
and RustFS rc.1 -> 1.0.3 rewrites metadata (upstream: no downgrade); the
recipe's own snapshot was `cp -al`, hardlinks a rewrite in place rewrites too.
tasks/one-way-upgrade-guard.yml stops the container, tars the data dir to
another volume and refuses unless the archive holds every file.
"""
from __future__ import annotations

import subprocess
import sys
import tarfile
from pathlib import Path

import jinja2
import yaml

REPO = Path(__file__).resolve().parents[2]
GUARD = REPO / "tasks" / "one-way-upgrade-guard.yml"
sys.path.insert(0, str(REPO / "tools"))
import nos_identity as ni  # noqa: E402


def _tasks():
    doc = yaml.safe_load(GUARD.read_text(encoding="utf-8"))
    return doc[0], doc[1]["block"]


def test_each_one_way_role_runs_the_guard_before_it_touches_the_data():
    for role, before in (("jellyfin", "Find stale SSO plugin versions"), ("rustfs", "Render compose override fragment")):
        names = [t.get("name", "") for t in yaml.safe_load((REPO / f"roles/pazny.{role}/tasks/main.yml").read_text())]
        guard = next(i for i, n in enumerate(names) if "One-way upgrade guard" in n)
        assert guard < next(i for i, n in enumerate(names) if before in n), f"{role}: guard after '{before}'"


def test_the_copy_goes_off_the_data_volume():
    v = ni.resolve_flag("one_way_upgrade_backup_dir", ni.default_layers())
    assert v and "nos_data_root" not in v[-1][1], v


def _run(script: str, tmp: Path, running: str) -> subprocess.CompletedProcess:
    fake = tmp / "docker"
    fake.write_text(f"#!/bin/sh\n[ \"$1 $2\" = 'ps -a' ] && echo '{running}'\nexit 0\n")
    fake.chmod(0o755)
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    body = env.from_string(script).render(
        docker_bin=str(fake), owg_name="svc", owg_service="svc", owg_pin="2.0",
        owg_data_dir=str(tmp / "data"), one_way_upgrade_backup_dir=str(tmp / "copies"),
        _owg_running={"stdout": running})
    return subprocess.run(["bash", "-c", body], capture_output=True, text=True, timeout=60)


def test_the_archive_holds_every_file_or_the_converge_stops(tmp_path):
    (tmp_path / "data" / "sub").mkdir(parents=True)
    for i in range(5):
        (tmp_path / "data" / "sub" / f"f{i}").write_text(str(i))
    _, block = _tasks()
    archive = next(t for t in block if "Archive" in t["name"])["ansible.builtin.shell"]
    done = _run(archive, tmp_path, "img:1.0")
    assert done.returncode == 0, done.stderr
    out = next((tmp_path / "copies").glob("svc-1.0-*.tar.gz"))
    assert oct(out.stat().st_mode)[-3:] == "600"
    with tarfile.open(out) as t:
        assert len([m for m in t.getmembers() if m.isfile()]) == 5

    short = archive.replace('tar -czf "$out"', 'tar -czf "$out" --exclude f0')
    assert _run(short, tmp_path, "img:1.0").returncode != 0, "a short archive must stop the converge"


def test_no_copy_on_first_install_or_when_the_tag_is_the_pin():
    _, block_when = _tasks()[1], yaml.safe_load(GUARD.read_text())[1]["when"]
    assert "_owg_running.stdout | trim | length > 0" in block_when
    assert any("!= owg_pin" in w for w in block_when)
