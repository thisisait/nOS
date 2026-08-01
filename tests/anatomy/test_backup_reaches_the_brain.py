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


# ── Absent is a failure, not a skip ─────────────────────────────────────────
#
# Measured 2026-08-01. `notify_result` derives severity purely from the recorded
# set: `failed = [x for x in sources if not x.get("success")]`, then
# `elif not sources: high`, `else: info; "Backup OK - N sources"`. A source that
# is ENABLED but whose data is ABSENT used to `continue`/`return 0` WITHOUT
# calling status_append — so it was neither failed nor absent-of-all, and landed
# in the info branch. An unmounted SSD or a moved nos_data_root dropped gitea,
# gitlab, wing.db (the audit hash-chain), ~/.nos secrets and the tofu tfstate
# out of the nightly set while the operator's inbox said "Backup OK".
#
# The asymmetry was visible in one function: run_wing_db recorded a failure when
# `sqlite3` was missing and returned silently when the DATABASE was missing, two
# lines apart.
#
# The rule: `DO_X != true` (deliberately disabled) may return silently — nobody
# asked for it. "Enabled but not there" must record success=0.


def _absent_source_branches() -> list[tuple[int, str]]:
    """Lines where an ENABLED source bails out because its data is not there.

    Keyed off the LOG line rather than the control-flow keyword: the one-liner
    guards (`|| { log ...; return 0; }`) and the multi-line `if` blocks put the
    bail-out and the message on different lines, and an earlier version of this
    matched only the one-liners — finding 3 of 5 and passing.
    """
    out = []
    for i, line in enumerate(BACKUP_SH.read_text().splitlines(), 1):
        s = line.strip()
        if s.startswith("#"):
            continue
        # A disabled-toggle guard is the legitimate silent return; nobody asked
        # for that source, so its absence is not a failure.
        if re.search(r'\[\[\s*"\$\{DO_\w+\}"\s*!=\s*"true"\s*\]\]', s):
            continue
        if "log " not in s:
            continue
        if re.search(r"(not found|missing|no token)", s):
            out.append((i, s))
    return out


def test_absent_source_branches_exist_at_all():
    """Guard the guard: if the detection regex stops matching, every assertion
    below passes by finding nothing."""
    assert len(_absent_source_branches()) >= 4, (
        "found almost no absent-source branches in backup.sh — the shapes "
        "changed and this gate silently stopped covering them"
    )


def test_an_absent_source_is_recorded_as_failed():
    src = BACKUP_SH.read_text().splitlines()
    offenders = []
    for lineno, stmt in _absent_source_branches():
        # The status_append may be on this line (one-liner guard) or within the
        # next few lines of an if-block.
        window = "\n".join(src[lineno - 1 : lineno + 4])
        if "status_append" not in window:
            offenders.append(f"backup.sh:{lineno}: {stmt[:100]}")
    assert not offenders, (
        "these bail out of an ENABLED source without recording anything, so "
        "notify_result counts them as neither failed nor missing and reports "
        '"Backup OK":\n  ' + "\n  ".join(offenders)
    )


# ── A failed send is not a delivered one ───────────────────────────────────
#
# Measured 2026-08-01, and it is the same disease as everything above: the
# sender wrote its own delivery record. `mark_dispatched()` stamped
# `{ntfy,mail}_dispatched_at` in BOTH branches, and `fetch_pending()` selects
# `WHERE {col} IS NULL` — so one unreachable moment for ntfy or the SMTP host
# excluded that row from every subsequent run, permanently, while leaving it
# indistinguishable in the database from a delivered one. The file's own
# docblock promised "Pulse re-tries on next tick"; the retry it promised could
# not happen.
#
# The alarm self-healed too: the failing run exits 2 → one "job failing" row;
# the next minute the row is already stamped, the run is clean → "job
# recovered". The operator sees a resolved blip and never sees the message.

DISPATCH_PHP = REPO / "files" / "anatomy" / "wing" / "bin" / "dispatch-notifications.php"


def test_a_failed_delivery_leaves_the_row_pending():
    src = DISPATCH_PHP.read_text()
    fn = src[src.index("function mark_dispatched"):]
    fn = fn[: fn.index("\n}\n")]
    # The success branch stamps; the failure branch must not stamp
    # unconditionally. A CASE guarded by the attempt budget is the only
    # stamping allowed on the error path.
    assert "CASE WHEN" in fn and "DISPATCH_MAX_ATTEMPTS" in fn, (
        "mark_dispatched no longer bounds its stamping by an attempt budget — if "
        "it stamps dispatched_at on failure, fetch_pending (WHERE col IS NULL) "
        "will never see the row again and a lost message reads as delivered"
    )
    error_branch = fn[fn.index("} else {"):]
    assert "= :ts," not in error_branch.split("CASE WHEN")[0].split("SET")[-1], (
        "the error branch assigns the timestamp directly again"
    )


def test_the_attempt_counters_exist_on_both_fresh_and_existing_dbs():
    """A column only in schema-extensions.sql never appears on an install that
    already ran: CREATE TABLE IF NOT EXISTS is a no-op there. It must ALSO be in
    init-db.php's idempotent ALTER sweep."""
    schema = (REPO / "files" / "anatomy" / "wing" / "db" / "schema-extensions.sql").read_text()
    initdb = (REPO / "files" / "anatomy" / "wing" / "bin" / "init-db.php").read_text()
    for col in ("ntfy_attempts", "mail_attempts"):
        assert col in schema, f"{col} missing from schema-extensions.sql (fresh installs)"
        assert col in initdb, (
            f"{col} missing from init-db.php's addMissingColumns sweep — every "
            f"EXISTING wing.db would lack it and the UPDATE would fail at runtime"
        )


def test_the_php_insert_path_defaults_by_severity_too():
    """Bone and Wing insert into the SAME notifications table.

    Bone's Python path learned this after six nights of 'Backup FAILED' at
    severity=high reached nobody. The PHP path kept `?? ['wing-inbox']`, so
    PulsePresenter's high-severity 'Pulse job X failing' — the single choke
    point that sees every run result — never reached a phone either, and repeat
    failures are suppressed by design, making one unread row the whole footprint
    of a permanently broken job.
    """
    repo = (REPO / "files" / "anatomy" / "wing" / "app" / "Model" / "NotificationRepository.php").read_text()
    assert "defaultChannelsFor" in repo, (
        "NotificationRepository lost its severity-aware default; an omitted "
        "`channels` is back to inbox-only at every severity"
    )
    m = re.search(r"function defaultChannelsFor.*?\}\s*\n\s*\}", repo, re.S)
    assert m and "'critical', 'high' => ['wing-inbox', 'ntfy']" in m.group(0), (
        "critical/high no longer default to ntfy in the PHP path, while Bone's "
        "Python twin still does — same table, two different loudness levels"
    )
