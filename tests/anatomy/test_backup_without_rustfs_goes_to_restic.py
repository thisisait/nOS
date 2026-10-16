"""Gate: a host without RustFS backs up with restic directly, dumps included.

2026-10-16, a core-profile client host: install_rustfs and install_backup off,
configure_backup on with a local restic_repo. Copy #2 mirrored rustfs_data_dir,
an empty bucket dir, so the client had no useful backup. Operator ruling: no
RustFS = no copy #1; the restic wrapper stages the DB dumps itself and snapshots
them with the installed services' data dirs. ONE derivation picks the path.

The wrapper is rendered by the REAL Ansible templar (a scratch localhost play
in tmp_path, HOME pointed there) and run with docker/restic stubbed on PATH.
"""
import gzip
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
BACKUP_YML = REPO / "tasks/backup.yml"
sys.path.insert(0, str(REPO / "tools"))
import nos_identity as ni  # noqa: E402

# Every call is recorded. KEAP's in-container node program gets its stdin eaten
# and "succeeds"; the follow-up `cat` of the snapshot returns marker bytes.
STUB_DOCKER = """#!/bin/bash
echo "$*" >> "$HOME/docker.calls"
case "$*" in
  *node*) cat > /dev/null ;;
  *" cat /tmp/"*) printf 'KEAP-SNAPSHOT' ;;
  *) echo "-- dumped by: $*" ;;
esac
"""
# Records every call; for `backup` it lists the files the snapshot would hold.
STUB_RESTIC = """#!/bin/bash
echo "$*" >> "$HOME/restic.calls"
if [[ "$1" == backup ]]; then
  for p in "$@"; do [[ -e "$p" ]] && find "$p" -type f -not -name '*.part'; done >> "$HOME/snapshot.txt"
fi
exit 0
"""


def _wrapper_content() -> str:
    tasks = yaml.safe_load(BACKUP_YML.read_text(encoding="utf-8"))
    task = next(t for t in tasks if "backup-run.sh wrapper" in t.get("name", ""))
    return task["ansible.builtin.copy"]["content"]


def render(tmp: Path, profile: str, extra: dict | None = None) -> Path:
    """Render backup-run.sh for `profile` with the real templar; returns its path."""
    stub = tmp / "stub"
    (stub / "bin").mkdir(parents=True, exist_ok=True)
    for name, body in (("docker", STUB_DOCKER), ("restic", STUB_RESTIC)):
        (stub / "bin" / name).write_text(body)
        (stub / "bin" / name).chmod(0o755)
    flags = ni.install_flags(ni.profile_layers(REPO / profile))
    out = tmp / "backup-run.sh"
    play = [{
        "hosts": "localhost", "connection": "local", "gather_facts": True,
        "gather_subset": ["!all", "min"],
        "vars_files": [str(p) for p in ni.default_layers()],
        "tasks": [
            {"name": "export the resolved derivation",
             "ansible.builtin.copy": {"content": "{{ backup_copy1_enabled | bool }}\n",
                                      "dest": str(tmp / "copy1.txt")}},
            {"name": "render the wrapper",
             "ansible.builtin.copy": {"content": _wrapper_content(), "dest": str(out), "mode": "0700"}},
        ],
    }]
    (tmp / "play.yml").write_text(yaml.safe_dump(play, sort_keys=False))
    ev = {**flags, "homebrew_prefix": str(stub), **(extra or {})}
    (tmp / "ev.json").write_text(json.dumps(ev))
    (tmp / "ansible.cfg").write_text("[defaults]\n")
    env = {**os.environ, "HOME": str(tmp), "ANSIBLE_LOCALHOST_WARNING": "false",
           "ANSIBLE_INVENTORY_UNPARSED_WARNING": "false", "ANSIBLE_CONFIG": str(tmp / "ansible.cfg")}
    run = subprocess.run([sys.executable, "-m", "ansible.cli.playbook", "-i", "localhost,", str(tmp / "play.yml"),
                          "-e", f"@{REPO / profile}", "-e", f"@{tmp / 'ev.json'}"],
                         cwd=tmp, env=env, capture_output=True, text=True)
    assert run.returncode == 0, run.stdout[-3000:] + run.stderr[-2000:]
    return out


def execute(tmp: Path, script: Path) -> subprocess.CompletedProcess:
    (tmp / ".nos").mkdir(exist_ok=True)
    (tmp / ".nos/restic.env").write_text("export NOS_PG_PASSWORD=stub NOS_MARIADB_PASSWORD=stub\n")
    env = {"HOME": str(tmp), "PATH": "/usr/bin:/bin"}
    return subprocess.run(["/bin/bash", str(script)], env=env, cwd=tmp, capture_output=True, text=True)


@pytest.fixture(scope="module")
def core(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("core")
    tenants = tmp / "nos/tenants/acme"
    tenants.mkdir(parents=True)
    (tenants / "invoice.pdf").write_text("pdf")
    (tmp / "wing/app/data").mkdir(parents=True)
    sqlite3.connect(tmp / "wing/app/data/wing.db").executescript("create table audit(x); insert into audit values ('w');")
    (tmp / ".nos").mkdir()
    (tmp / ".nos/secrets.yml").write_text("k: v\n")
    (tmp / ".nos/state.yml").write_text("s: 1\n")
    (tmp / "terraform/authentik").mkdir(parents=True)
    (tmp / "terraform/authentik/terraform.tfstate").write_text("{}")
    script = render(tmp, "profiles/core.yml")
    return tmp, script, execute(tmp, script)


def test_the_derivation_is_off_on_core_and_on_by_default(core, tmp_path):
    tmp, *_ = core
    assert (tmp / "copy1.txt").read_text().strip() == "False", "core has no RustFS: copy #1 must be off"
    render(tmp_path, "profiles/all-on.yml")
    assert (tmp_path / "copy1.txt").read_text().strip() == "True"


def test_the_snapshot_holds_the_postgres_dump(core):
    tmp, _, run = core
    staging = tmp / "backups/staging"
    dump = staging / "postgres.sql.gz"
    assert dump.is_file(), run.stdout + run.stderr + (tmp / "backups/backup.log").read_text()
    assert b"pg_dumpall" in gzip.decompress(dump.read_bytes())
    assert not (staging / "mariadb.sql.gz").exists(), "core has no MariaDB"
    snap = (tmp / "snapshot.txt").read_text().splitlines()
    assert str(dump) in snap, snap
    assert str(tmp / "nos/tenants/acme/invoice.pdf") in snap, "an installed data dir is not in the snapshot"
    calls = (tmp / "restic.calls").read_text()
    assert "rustfs" not in calls, f"the direct path still names the RustFS bucket: {calls}"


def test_the_direct_run_writes_its_own_status(core):
    tmp, *_ = core
    status = json.loads((tmp / ".nos/backup-restic-status.json").read_text())
    by = {s["name"]: s for s in status["sources"]}
    assert by["postgres"]["success"] is True
    assert "mariadb" not in by


def test_with_rustfs_the_wrapper_still_mirrors_the_bucket(tmp_path):
    bucket = tmp_path / "nos/platform/services/rustfs/data"
    bucket.mkdir(parents=True)
    (bucket / "obj").write_text("x")
    script = render(tmp_path, "profiles/all-on.yml")
    execute(tmp_path, script)
    calls = (tmp_path / "restic.calls").read_text()
    assert f"backup --exclude-file={tmp_path}/backups/.resticignore {bucket}" in calls, calls
    assert not (tmp_path / "backups/staging/postgres.sql.gz").exists(), "copy #1 owns the dumps there"


def test_an_off_dir_with_data_rides_the_direct_snapshot(tmp_path):
    """Ruling 2026-10-16, direct path: off + data = in, marked off; off +
    empty/absent = ignored; on + absent = FAILED."""
    vault, book = tmp_path / "vault", tmp_path / "book"
    vault.mkdir()
    book.mkdir()
    (vault / "db.sqlite3").write_text("x")
    dirs = [{"name": "vaultwarden", "flag": "install_vaultwarden", "path": str(vault)},
            {"name": "bookstack", "flag": "install_bookstack", "path": str(book)},
            {"name": "mikopbx", "flag": "install_mikopbx", "path": str(tmp_path / "none")},
            {"name": "gitea", "flag": "install_gitea", "path": str(tmp_path / "gone")}]
    script = render(tmp_path, "profiles/core.yml", {"backup_dirs_to_dump": dirs, "install_gitea": True})
    execute(tmp_path, script)
    snap = (tmp_path / "snapshot.txt").read_text()
    by = {s["name"]: s for s in json.loads((tmp_path / ".nos/backup-restic-status.json").read_text())["sources"]}
    assert str(vault / "db.sqlite3") in snap and by["dir-vaultwarden"]["off"] is True, by
    assert "dir-bookstack" not in by and "dir-mikopbx" not in by, by
    assert by["dir-gitea"]["success"] is False


def test_the_core_snapshot_holds_keap_wing_state_and_tofu(core):
    """Operator ruling 2026-10-16 (Q1): the direct path carries what copy #1 did."""
    tmp, _, run = core
    staging = tmp / "backups/staging"
    snap = (tmp / "snapshot.txt").read_text().splitlines()
    assert gzip.decompress((staging / "keap-db.gz").read_bytes()) == b"KEAP-SNAPSHOT", run.stderr
    assert b"insert into" in gzip.decompress((staging / "wing-db.sql.gz").read_bytes()).lower()
    for f in (staging / "keap-db.gz", staging / "wing-db.sql.gz", tmp / ".nos/secrets.yml",
              tmp / ".nos/state.yml", tmp / "terraform/authentik/terraform.tfstate"):
        assert str(f) in snap, f"{f} is not in the snapshot"
    assert not list(staging.glob("*secrets*")) and not list(staging.glob("nos-state*")), (
        "~/.nos state must reach restic in place, never as a second plaintext copy")
    by = {s["name"]: s["success"] for s in json.loads((tmp / ".nos/backup-restic-status.json").read_text())["sources"]}
    assert by.get("keap-db") and by.get("wing-db") and by.get("nos-state") and by.get("tofu-state"), by


def test_the_keap_dump_is_taken_inside_the_container(core):
    tmp, *_ = core
    calls = (tmp / "docker.calls").read_text()
    assert "exec -i iiab-keap-1 sh -c" in calls and "node --no-warnings" in calls, calls


def test_rustfs_on_without_install_backup_does_not_mirror_the_bucket(tmp_path):
    """Ruling 2026-10-16 (Q2): RustFS without copy #1 = the direct path only. A pin:
    green since 0b3ba384, which derives copy #1 from both flags."""
    bucket = tmp_path / "nos/platform/services/rustfs/data"
    bucket.mkdir(parents=True)
    (bucket / "obj").write_text("x")
    script = render(tmp_path, "profiles/core.yml", {"install_rustfs": True})
    assert (tmp_path / "copy1.txt").read_text().strip() == "False"
    execute(tmp_path, script)
    assert str(bucket) not in (tmp_path / "restic.calls").read_text()
    assert (tmp_path / "backups/staging/postgres.sql.gz").is_file()
