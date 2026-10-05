"""Anatomy gate: KEAP captures survive a removal (pins the pre-wipe survivor).

Trigger: the 128-lost-captures incident (2026-07-25). KEAP captures are
keap.db ROWS — no on-disk blobs (verified against the live store: /data holds
only keap.db + WAL). The daily keap.db dump lands in copy #1 (the RustFS
bucket), which `remove=data` ALSO wipes — so without an off-site survivor the
captures are gone without a trace.

This gate pins the FOUR load-bearing invariants of the fix so none can silently
regress:

  1. keap.db IS backed up by default when install_keap (backup_keap_db default).
  2. keap.db HAS a restore target (a backup with no restore is a latent second
     data-loss hole).
  3. keap_data_dir IS in the removal set (documents remove=data wipes it, so the
     backup is load-bearing, not decorative).
  4. main.yml takes a CONFIRMED-only pre-wipe off-site snapshot, gated on
     restic_repo being set, via SYNCHRONOUS restic (no async race with the
     wipe) with the password in RESTIC_PASSWORD env (never argv) + fail-soft;
     and the dry-run inventory LOUDLY flags permanent loss when restic_repo is
     unset.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKUP_DEFAULTS = REPO_ROOT / "roles" / "pazny.backup" / "defaults" / "main.yml"
RESTORE_PATH = REPO_ROOT / "tasks" / "restore.yml"
REMOVAL_SET_PATH = REPO_ROOT / "tasks" / "removal-set.yml"
MAIN_PATH = REPO_ROOT / "main.yml"
PREWIPE_PATH = REPO_ROOT / "tasks" / "pre-wipe-backup.yml"
RUNMODE_PATH = REPO_ROOT / "tasks" / "run-mode.yml"


def test_keap_db_backup_enabled_by_default_with_keap() -> None:
    """backup_keap_db keys off install_keap → the dump runs whenever KEAP does."""
    txt = BACKUP_DEFAULTS.read_text()
    assert "backup_keap_db:" in txt, "backup_keap_db default missing"
    # default expression must reference install_keap (not a hardcoded false)
    line = next(ln for ln in txt.splitlines() if ln.strip().startswith("backup_keap_db:"))
    assert "install_keap" in line, f"backup_keap_db must key off install_keap: {line!r}"


def test_keap_db_has_a_restore_target() -> None:
    """A backup with no restore path is a latent second data-loss hole."""
    txt = RESTORE_PATH.read_text()
    assert "keap-db" in txt, "restore.yml has no keap-db restore block"
    assert "keap.db" in txt, "restore.yml keap-db block does not name keap.db"


def test_keap_data_dir_is_wiped_by_removal() -> None:
    """remove=data wipes keap_data_dir → the backup is load-bearing."""
    txt = REMOVAL_SET_PATH.read_text()
    assert "keap_data_dir" in txt, "keap_data_dir absent from removal-set (would orphan)"


def test_prewipe_survivor_check_runs_on_every_confirmed_removal() -> None:
    """Review 2026-10-04: gated on install_keap + restic_repo, the import (and its
    'no survivor, no wipe' verdict) vanished exactly when no survivor existed, so
    `nos --remove=all -y` without restic_repo wiped with no backup. Parse the when."""
    import yaml
    play = yaml.safe_load(MAIN_PATH.read_text())
    tasks = [t for p in play for t in p.get("tasks") or []]
    paths = [str(t.get("import_tasks", "")) for t in tasks]
    pre = tasks[paths.index("tasks/pre-wipe-backup.yml")]
    when = " ".join(pre["when"] if isinstance(pre["when"], list) else [pre["when"]])
    assert "nos_removing" in when, when
    for leak in ("install_keap", "restic_repo"):
        assert leak not in when, f"the survivor check must not depend on {leak}: {when}"
    assert paths.index("tasks/pre-wipe-backup.yml") < paths.index("tasks/blank-reset.yml"), (
        "pre-wipe snapshot must run BEFORE blank-reset deletes copy #1"
    )


def test_prewipe_task_is_synchronous_failsoft_and_secret_safe() -> None:
    """Synchronous restic (no async race), fail-soft, password never in argv."""
    txt = PREWIPE_PATH.read_text()
    assert "restic" in txt, "pre-wipe must use restic for the off-site snapshot"
    assert "RESTIC_PASSWORD" in txt, "password must ride RESTIC_PASSWORD env"
    # password must NOT appear on a command line (only in environment:)
    for ln in txt.splitlines():
        if "restic_password" in ln:
            assert "RESTIC_PASSWORD" in ln, f"restic_password leaked outside env: {ln!r}"
    # every restic invocation is fail-soft (a backup hiccup never blocks the wipe)
    assert txt.count("failed_when: false") >= 3, "pre-wipe restic steps must be fail-soft"
    assert "no_log: true" in txt, "restic steps handling the password must be no_log"


def test_inventory_warns_on_missing_offsite_repo() -> None:
    """Dry-run inventory LOUDLY flags permanent capture loss when restic_repo unset."""
    txt = RUNMODE_PATH.read_text()
    assert "KEAP captures" in txt, "removal inventory does not mention KEAP captures"
    assert "PERMANENTLY LOST" in txt, "inventory must warn of permanent loss when repo unset"
    assert "restic_repo" in txt, "inventory warning must reference restic_repo"


def test_the_pre_wipe_snapshot_carries_the_plaintext_staging_dir():
    """2026-09-30: the fresh pre-blank KEAP dump existed only as 49 bitrot-framed
    RustFS parts in the snapshot; the plaintext staging copy of the same dump
    was never snapshotted. Render the command and read its paths."""
    import jinja2, yaml
    tasks = yaml.safe_load(PREWIPE_PATH.read_text(encoding="utf-8"))
    snap = next(t for t in tasks if "SYNCHRONOUS off-site snapshot" in t.get("name", ""))
    cmd = jinja2.Environment().from_string(snap["ansible.builtin.command"]).render(
        restic_repo="/r", rustfs_data_dir="/rustfs", backup_staging_dir="/home/u/backups/staging",
        remove="all", ansible_facts={"env": {"HOME": "/home/u"}})
    argv = cmd.split()
    assert "/rustfs" in argv and "/home/u/backups/staging" in argv, argv
    assert "'*.part'" in argv, "a half-written dump must not enter the survivor"
    names = [t.get("name", "") for t in tasks]
    refresh = next(i for i, n in enumerate(names) if "Refresh copy #1" in n)
    assert refresh < names.index(snap["name"]), "the fresh dump must precede the snapshot"
