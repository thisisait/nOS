"""Anatomy gate — the backup must cover the brain, and must be able to say it didn't.

Found 2026-07-30, the night before a scheduled blank. Three independent defects
lined up so that the single most valuable store in the estate had never once been
backed up, and nobody knew:

  1. `backup.sh` runs from launchd (`eu.thisisait.nos.backup.rustfs.plist`), whose
     context has NO Full Disk Access for /Volumes. `nos_data_root` IS
     `/Volumes/SSD1TB/nOS/data`, so every host-path source under it failed with
     `authorization denied` — 7 of 7 on the external disk, 0 of 7 elsewhere. The
     same `sqlite3 .backup` run from an interactive shell completes in 2.2 s.

  2. Every `run_*` returns 0 by design (one broken source must not abort the
     rest), so the script's own exit code could not distinguish "all good" from
     "the brain is missing". `tasks/pre-wipe-backup.yml` checks exactly that rc,
     and so printed "✓ copy #1 refreshed" over a bucket with no KEAP data in it
     — every night, right before offering to wipe.

  3. The failure notification WAS raised, at severity=high, six nights running.
     It reached nobody: `backup.sh` posts `origin_plugin: "backup"`, no plugin
     manifest owns that name, and an unrouted origin fell back to
     ["wing-inbox"] alone while all 56 registered plugins route on_high to ntfy
     as well. All six are still unread.

The fixes are pinned here, not because the code is subtle, but because each one
was invisible for weeks and would be again.

CI-safe: source scan only. No Docker, no live host, no network.
"""
from __future__ import annotations

import pathlib
import re

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
BACKUP_SH = REPO / "roles" / "pazny.backup" / "files" / "backup.sh"
BACKUP_DEFAULTS = REPO / "roles" / "pazny.backup" / "defaults" / "main.yml"
WING_CLIENT = REPO / "files" / "anatomy" / "bone" / "clients" / "wing.py"
PRE_WIPE = REPO / "tasks" / "pre-wipe-backup.yml"


def _sh() -> str:
    return BACKUP_SH.read_text()


def _sh_code() -> str:
    """backup.sh with comment lines stripped.

    The file explains at length WHY `VACUUM INTO` is wrong here, so a naive
    substring check fails on the explanation rather than on a regression.
    """
    return "\n".join(
        ln for ln in BACKUP_SH.read_text().splitlines() if not ln.lstrip().startswith("#")
    )


# ── 1. the brain is reachable without a GUI permission grant ──────────────


def test_keap_backup_runs_inside_the_container():
    """The primary path must not depend on the launchd context's disk access."""
    s = _sh()
    body = s[s.index("run_keap_db()"):]
    assert 'docker exec' in body and '${KEAP_CONTAINER}' in body, (
        "run_keap_db no longer backs up through the container. A host-side read "
        "of keap.db under nos_data_root fails with 'authorization denied' from "
        "launchd — that is why this source never once succeeded."
    )
    # The container path must come BEFORE the host fallback, or we are back to
    # the original failure with extra steps.
    assert body.index("docker exec") < body.index("sqlite3"), (
        "the host sqlite3 path now runs before the container path — the "
        "container path is the one that works unattended"
    )


def test_keap_backup_does_not_use_vacuum_into():
    """`VACUUM INTO` cannot copy this store, and failed silently when it tried."""
    s = _sh_code()
    assert "VACUUM INTO" not in s.upper(), (
        "VACUUM INTO rebuilds every object including the libSQL vector index, "
        "and stock SQLite has no libsql_vector_idx() — it aborts with 'SQL "
        "logic error'. Use the page-level backup() API, which never parses the "
        "schema."
    )
    assert "backup(db, dst)" in s, "the node:sqlite page-level backup() call is gone"


def test_keap_container_is_configurable():
    d = yaml.safe_load(BACKUP_DEFAULTS.read_text())
    assert "backup_keap_container" in d
    assert "backup_keap_db_container_path" in d


def test_tcc_failure_is_named_not_just_logged():
    """A bare rc sent us to a 47 MB log for five nights. Name the cause."""
    s = _sh()
    assert "authorization denied" in s, (
        "the host fallback no longer recognises the macOS TCC error, so the "
        "one actionable diagnosis is lost again"
    )


# ── 2. a backup that lost a source must not look like a clean run ─────────


def test_backup_exits_non_zero_when_a_source_failed():
    s = _sh()
    main = s[s.index("main() {"):]
    assert "return 1" in main, (
        "main() no longer fails when a source failed. pre-wipe-backup.yml gates "
        "on this exit code and will go back to printing a green banner over a "
        "bucket that is missing the brain."
    )
    assert 'if not x.get("success")' in main, (
        "main() no longer reads the per-source success flags it is supposed to "
        "aggregate"
    )


def test_pre_wipe_banner_names_the_failed_sources():
    y = PRE_WIPE.read_text()
    assert "_prewipe_failed_sources" in y, (
        "the pre-wipe banner stopped enumerating which sources failed — 'backup.sh "
        "returned non-zero' sends the operator to a huge log at the worst moment"
    )
    assert "ABORT" in y


# ── 3. an alarm nobody can receive is not an alarm ────────────────────────


def test_unrouted_origin_still_reaches_ntfy_at_high():
    """The exact hole that swallowed six nights of 'Backup FAILED'."""
    src = WING_CLIENT.read_text()
    assert "_DEFAULT_CHANNELS_BY_SEVERITY" in src, (
        "the severity-aware fallback is gone; an origin with no routing entry "
        "is back to inbox-only at every severity"
    )
    m = re.search(r"_DEFAULT_CHANNELS_BY_SEVERITY\s*=\s*\{(.*?)\}", src, re.S)
    assert m, "could not parse the fallback table"
    table = m.group(1)
    for sev in ("critical", "high"):
        row = re.search(rf'"{sev}":\s*\[([^\]]*)\]', table)
        assert row and "ntfy" in row.group(1), (
            f"severity={sev} no longer falls back to ntfy. roles/pazny.backup is "
            f"a host role with no plugin manifest, so its notifications resolve "
            f"to no entry — inbox-only means unread."
        )


def test_no_caller_hardcodes_the_inbox_only_fallback():
    src = WING_CLIENT.read_text()
    # The literal is fine inside the table and the docstrings; it must not be
    # the thing an unmatched lookup falls through to.
    assert 'else ["wing-inbox"]' not in src, (
        'an "else [\\"wing-inbox\\"]" fallback is back in the channel resolution '
        "path — use _default_channels(severity)"
    )
