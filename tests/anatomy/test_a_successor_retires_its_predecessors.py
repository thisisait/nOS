"""A notification that stopped being true has a way to stop being unread.

WHAT WAS MEASURED, 2026-08-23. 76 unread rows in the Wing inbox, oldest 29
days, and 60 of them were repeating classes where each new send makes its
predecessor false by construction:

    os-resume               27 + 3 + 1
    backup / backup-verify  19 + 5 + 1
    prometheus-alert-relay  7 + 2 + 1
    security-drift          4

The four `security-drift` rows each said "1 critical, 11 high pending". All
four were TRUE WHEN SENT and none was true by that afternoon. A notification is
an EVENT and the inbox is a STATE (`docs/hidden_fees/26`), and nothing joined
them for report rows.

WHY NOT `read`. Marking them read is the estate telling itself a lie about a
human: nobody read them. So this is a THIRD state — `superseded_at` — and the
row stays reachable (`include_superseded`, `countSuperseded`) because hiding a
row with no way to see it is indistinguishable from deleting it.

WHY NOT INFERRED FROM `origin_plugin`. Two gitleaks findings are two different
secrets; two prometheus alerts are two different alarms. Only the SENDER knows
whether its new message replaces the old one or joins it, so `supersede_key` is
declared by the emitter and a row without one is never touched. That is the
same authorship rule as the session reaper (`docs/hidden_fees/25`).

WHAT THIS IS NOT. It does not decide whether a condition CLEARED — that is
`bin/reconcile-inbox.php`, which marks a row read only after reading the
condition's own source, and which deliberately leaves report rows alone
("a report row is news, not state"). Two mechanisms, two questions: *did it
clear* and *has it been re-said*. Neither may do the other's job.
"""

from __future__ import annotations

import importlib
import pathlib
import sqlite3
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
SCHEMA = REPO / "files/anatomy/wing/db/schema-extensions.sql"
INITDB = REPO / "files/anatomy/wing/bin/init-db.php"
BONE = REPO / "files/anatomy/bone"

COLUMNS = ("supersede_key", "superseded_at", "superseded_by")

#: Emitters that opted in, and the class each declares. Measured populations
#: are in the module docstring; every one of these is a REPORT whose successor
#: restates it, never a finding about a distinct thing.
EMITTERS = {
    "files/anatomy/scripts/nos-os-resume.sh": "os-resume-settled",
    "roles/pazny.backup/files/backup.sh": "backup-nightly-result",
    "roles/pazny.backup/files/backup-verify.sh": "backup-restore-drill",
    "files/anatomy/scripts/drift-watch.sh": "security-drift-verdict",
}


# ── the schema exists in BOTH places ───────────────────────────────────────


def test_the_columns_are_declared_for_a_fresh_install():
    src = SCHEMA.read_text(encoding="utf-8")
    body = src[src.index("CREATE TABLE IF NOT EXISTS notifications"):]
    body = body[:body.index(");")]
    for col in COLUMNS:
        assert col in body, f"{col} missing from the notifications CREATE TABLE"


def test_an_existing_database_gets_them_too():
    """`CREATE TABLE IF NOT EXISTS` is a NO-OP on the 979 MB database that
    actually holds the backlog. Without the ALTER sweep the feature would be
    live only where there is nothing to fix — the exact failure
    `test_backup_reaches_the_brain.py` names for another column."""
    php = INITDB.read_text(encoding="utf-8")
    sweep = php[php.index("$addMissingColumns($db, 'notifications'"):]
    for col in COLUMNS:
        assert f"'{col}'" in sweep, (
            f"{col} is declared for fresh installs but never ALTER'd into an "
            "existing one — dead where it matters")


# ── the behaviour, against a real database ────────────────────────────────


@pytest.fixture()
def store(tmp_path, monkeypatch):
    db = tmp_path / "wing.db"
    src = SCHEMA.read_text(encoding="utf-8")
    start = src.index("CREATE TABLE IF NOT EXISTS notifications")
    end = src.index("CREATE INDEX IF NOT EXISTS idx_notifications_created_at")
    conn = sqlite3.connect(db)
    conn.executescript(src[start:end])
    conn.commit()
    conn.close()

    monkeypatch.setenv("WING_DB_PATH", str(db))
    monkeypatch.syspath_prepend(str(BONE))
    for name in [m for m in list(sys.modules) if m.startswith("clients")]:
        del sys.modules[name]
    wing = importlib.import_module("clients.wing")
    return db, wing


def _rows(db):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        return {r["title"]: dict(r) for r in
                conn.execute("SELECT * FROM notifications")}
    finally:
        conn.close()


def test_a_successor_retires_only_its_own_class(store):
    db, wing = store
    for title, key in (("resume 1", "os-resume-settled"),
                       ("backup 1", "backup-nightly-result"),
                       ("finding X", None),
                       ("resume 2", "os-resume-settled")):
        payload = {"severity": "info", "title": title}
        if key:
            payload["supersede_key"] = key
        wing.insert_notification(payload)

    rows = _rows(db)
    assert rows["resume 1"]["superseded_at"], "the predecessor was not retired"
    assert rows["resume 1"]["superseded_by"] == rows["resume 2"]["uuid"], (
        "superseded_by must name the successor — without the lineage the row "
        "is hidden with no way to ask why")
    assert not rows["resume 2"]["superseded_at"], "the newest row retired itself"
    assert not rows["backup 1"]["superseded_at"], (
        "a different class was retired; supersede_key is a WHERE key over a "
        "shared table and this is the way it goes wrong")
    assert not rows["finding X"]["superseded_at"], (
        "a row with NO key was retired. Emitters that do not opt in are "
        "reporting distinct things — two gitleaks findings are two secrets")


def test_superseding_is_not_marking_read(store):
    """The whole reason for a third column. `read` is a claim about a human."""
    db, wing = store
    wing.insert_notification({"severity": "info", "title": "a",
                              "supersede_key": "k"})
    wing.insert_notification({"severity": "info", "title": "b",
                              "supersede_key": "k"})
    assert _rows(db)["a"]["wing_inbox_read_at"] is None, (
        "the retired row was marked read — nobody read it, and the inbox would "
        "be recording a decision the operator never made")


def test_a_row_the_operator_already_read_is_left_alone(store):
    db, wing = store
    wing.insert_notification({"severity": "info", "title": "a", "supersede_key": "k"})
    conn = sqlite3.connect(db)
    conn.execute("UPDATE notifications SET wing_inbox_read_at = datetime('now')")
    conn.commit()
    conn.close()
    wing.insert_notification({"severity": "info", "title": "b", "supersede_key": "k"})
    assert _rows(db)["a"]["superseded_at"] is None, (
        "a row the operator has read is a decided row; re-stamping it as "
        "superseded overwrites their decision with the machine's")


def test_the_unread_query_stops_counting_a_retired_row(store):
    db, wing = store
    for t in ("a", "b"):
        wing.insert_notification({"severity": "info", "title": t, "supersede_key": "k"})
    live = wing.query_notifications(unread_only=True)
    assert [n["title"] for n in live] == ["b"], (
        "the write happened and the read ignored it — the row would still be "
        "counted, which is the entire defect")
    both = wing.query_notifications(unread_only=True, include_superseded=True)
    assert len(both) == 2, (
        "there must be a way to see a retired row; hiding it with no audit "
        "view is indistinguishable from deleting it")


def test_the_insert_and_the_supersede_share_one_transaction(store):
    """Retiring first and crashing empties the inbox of a live class; inserting
    first and crashing leaves the duplicate. Read structurally — a crash is not
    reproducible here, but the two statements sharing one `with _open()` is."""
    src = (BONE / "clients/wing.py").read_text(encoding="utf-8")
    fn = src[src.index("def insert_notification"):]
    fn = fn[:fn.index("\ndef ", 10)]
    body = fn[fn.index("with _open() as conn:"):]
    assert "UPDATE notifications" in body and "INSERT INTO notifications" in body, (
        "the supersede UPDATE moved outside the insert's transaction")
    assert body.count("with _open()") == 1, "two connections, two transactions"


# ── the emitters, and the readers ─────────────────────────────────────────


def test_the_emitters_that_repeat_actually_declare_a_class():
    """A feature nothing uses is the shape of `docs/hidden_fees/28`: it
    renders, it resolves, and the 60 rows stay."""
    for rel, key in EMITTERS.items():
        src = (REPO / rel).read_text(encoding="utf-8")
        assert key in src, (
            f"{rel} no longer declares supersede_key {key!r} — its repeating "
            "rows go back to accumulating, silently")


def test_a_loose_key_is_refused_before_it_reaches_the_table():
    """`supersede_key` becomes a WHERE key over a table every emitter shares.
    A wildcard-ish or oversized value retires somebody else's rows."""
    sys.path.insert(0, str(BONE))
    for mod in ("notifications",):
        sys.modules.pop(mod, None)
    notifications = importlib.import_module("notifications")
    ok = {"severity": "info", "title": "t", "supersede_key": "backup-nightly-result"}
    assert notifications.validate_payload(ok) is None
    for bad in ("", "A-B", "x" * 80, "has space", "-leading", 42, "sql'inject"):
        payload = {"severity": "info", "title": "t", "supersede_key": bad}
        assert notifications.validate_payload(payload) is not None, (
            f"supersede_key {bad!r} was accepted")


def test_every_unread_reader_excludes_a_retired_row():
    """Four places count unread. One of them missing this clause is how the
    badge and the inbox come to disagree — and the reader is believed."""
    repo_php = (REPO / "files/anatomy/wing/app/Model/NotificationRepository.php"
                ).read_text(encoding="utf-8")
    count_unread = repo_php[repo_php.index("function countUnread"):]
    count_unread = count_unread[:count_unread.index("\n\t}")]
    assert "superseded_at" in count_unread, (
        "the navbar badge still counts retired rows")
    query = repo_php[repo_php.index("if (!empty($filters['unread_only']))"):]
    assert "superseded_at" in query[:600], "the inbox list still shows them"

    red = (REPO / "tools/red-status.py").read_text(encoding="utf-8")
    assert "superseded_at IS NULL" in red, (
        "tools/red-status.py still reports retired rows as red — and it is the "
        "first thing a session runs")
    assert "PRAGMA table_info(notifications)" in red, (
        "the reader must ASK whether the column exists before querying it — a "
        "host whose converge has not yet run the ALTER sweep would raise, and "
        "red-status is the first thing a session runs. Keyed on the mechanism "
        "rather than a helper's name, which is what this assertion tripped on")


def _swept_columns() -> dict[str, set[str]]:
    """Every column init-db.php ALTERs in, per table.

    Parsed from the `$addMissingColumns($db, 'table', [ 'col' => 'TYPE', ])`
    calls rather than grepped for names, so a new sweep is covered the day it
    is written."""
    import re
    php = INITDB.read_text(encoding="utf-8")
    out: dict[str, set[str]] = {}
    for m in re.finditer(r"\$addMissingColumns\(\$db,\s*'([a-z_]+)',\s*\[(.*?)\]\s*\)",
                         php, re.S):
        table, body = m.group(1), m.group(2)
        out.setdefault(table, set()).update(re.findall(r"'([a-z_]+)'\s*=>", body))
    return out


def test_no_index_here_depends_on_a_swept_in_column():
    """THE BUG THAT KILLED A CONVERGE, 2026-08-23.

    `CREATE TABLE IF NOT EXISTS` is a NO-OP on an existing database, so a
    column that arrives via the ALTER sweep does NOT exist while
    schema-extensions.sql is running — the sweep is later, in init-db.php. An
    index in this file that names such a column aborts the entire script:

        no such column: supersede_key

    and the play dies at `[pazny.wing] Initialize SQLite schema BEFORE daemon
    start`. It is invisible on a fresh database, where the CREATE TABLE really
    did make the column, which is exactly why it survived every local test:
    the temp-DB fixture above builds fresh tables and was green throughout.

    An index on a swept-in column belongs beside its sweep, where the columns
    are guaranteed to exist.

    This gate shipped with a KNOWN_LATENT ratchet of nine pre-existing
    instances. All nine were verified (2026-08-23) to be exact duplicates of
    indexes init-db.php already creates AFTER their sweeps — init-db.php is
    this file's only executor, so the schema-extensions.sql copies were
    deleted and the ratchet with them. The exported contract
    (`skills/contracts/wing.db-schema.sql`) is built from the finished DB, so
    the indexes survive in it — only their whitespace changed, because
    sqlite_master keeps the DDL as its author spelled it and init-db.php now
    IS the author (regenerated in the same commit)."""
    sql = SCHEMA.read_text(encoding="utf-8")
    swept = _swept_columns()
    assert swept, "no $addMissingColumns calls parsed — check this gate, not the sweep"

    offenders: list[str] = []
    for stmt in sql.split(";"):
        # STRIP COMMENTS FIRST, THEN look for the verb. The first cut checked
        # `stmt.strip().startswith("CREATE INDEX")` on the raw chunk — and
        # every statement in this file is preceded by a comment block, so the
        # chunk starts with `--` and was skipped. It found nine real instances
        # and MISSED the exact bug it was written for when that bug was
        # re-introduced under its own explanatory comment. Proven both
        # directions before being trusted.
        code = "\n".join(ln for ln in stmt.splitlines()
                         if not ln.lstrip().startswith("--")).strip()
        if not code.upper().startswith("CREATE INDEX"):
            continue
        for table, columns in swept.items():
            if f"ON {table}(" not in code and f"ON {table} (" not in code:
                continue
            for col in columns:
                import re as _re
                if _re.search(rf"(?<![\w]){_re.escape(col)}(?![\w])", code):
                    offenders.append(
                        f"index on {table} references {col!r}, which arrives "
                        f"via the ALTER sweep and does not exist here")
    assert not offenders, (
        "schema-extensions.sql would abort on any EXISTING database:\n  "
        + "\n  ".join(offenders)
        + "\nMove the index next to its $addMissingColumns call in "
          "bin/init-db.php. A fresh-DB test cannot see this.")


def test_the_index_exists_where_the_columns_do():
    """Having moved it, it must actually be somewhere — an index deleted in the
    name of fixing this would leave the supersede lookup a table scan."""
    php = INITDB.read_text(encoding="utf-8")
    assert "idx_notifications_supersede" in php, (
        "the supersede index is in neither file; it belongs beside its sweep")
    sweep_at = php.index("'supersede_key' => 'TEXT'")
    index_at = php.index("idx_notifications_supersede")
    assert index_at > sweep_at, (
        "the index is created BEFORE the columns are ALTER'd in — same failure "
        "one file along")


# ── the reconciler's half: retiring what predates the mechanism ────────────
#
# The emitters retire their own successors from now on. They cannot retire what
# they sent BEFORE `supersede_key` existed — the UPDATE matches on the key and
# every historical row has none. Measured 2026-08-24, the morning after the
# mechanism shipped: the 01:02 backup emitted WITH its key and retired ZERO,
# and 57 rows the feature was built for sat exactly where they were.
#
# `bin/reconcile-inbox.php` is where that belongs. It already decides only on
# evidence, and it now has evidence for report rows: a later message from the
# same sender. What it must NOT do is reach for the column it already knows —
# `wing_inbox_read_at` — because nobody read them.

RECONCILER = REPO / "files/anatomy/wing/bin/reconcile-inbox.php"


def _php() -> str | None:
    import shutil
    return shutil.which("php")


def _reconciler_db(tmp_path, rows):
    """A database with the notifications table and `rows` = (title, plugin,
    actor, key, created_at, read_at)."""
    db = tmp_path / "wing.db"
    src = SCHEMA.read_text(encoding="utf-8")
    start = src.index("CREATE TABLE IF NOT EXISTS notifications")
    end = src.index("CREATE INDEX IF NOT EXISTS idx_notifications_created_at")
    conn = sqlite3.connect(db)
    conn.executescript(src[start:end])
    for i, (title, plugin, actor, key, created, read_at) in enumerate(rows):
        conn.execute(
            "INSERT INTO notifications (uuid, severity, title, origin_plugin, "
            "actor_id, supersede_key, created_at, wing_inbox_read_at, target_actor_id) "
            "VALUES (?,?,?,?,?,?,?,?,'operator')",
            (f"uuid-{i}", "info", title, plugin, actor, key, created, read_at))
    conn.commit()
    conn.close()
    return db


def _run_reconciler(db, *args):
    import os
    return subprocess.run(
        ["php", str(RECONCILER), *args],
        capture_output=True, text=True, timeout=120,
        env=dict(os.environ, WING_DB_PATH=str(db)))


def _state(db):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        return {r["title"]: dict(r) for r in conn.execute("SELECT * FROM notifications")}
    finally:
        conn.close()


@pytest.mark.skipif(_php() is None, reason="php absent — the reconciler cannot run")
def test_the_reconciler_retires_without_claiming_anyone_read_it():
    """The one property that cannot be traded away. `read` is a claim about a
    human; these rows were never read, and an inbox that records a decision the
    operator never made is worse than one that is merely long."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        db = _reconciler_db(tmp, [
            ("Backup OK - 1", "backup", "backup", None, "2026-08-01 01:00:00", None),
            ("Backup OK - 2", "backup", "backup", None, "2026-08-02 01:00:00", None),
            ("Backup OK - 3", "backup", "backup", "backup-nightly-result",
             "2026-08-03 01:00:00", None),
        ])
        out = _run_reconciler(db, "--apply")
        assert out.returncode in (0, 2), out.stderr[-400:]
        rows = _state(db)
        for stale in ("Backup OK - 1", "Backup OK - 2"):
            assert rows[stale]["superseded_at"], f"{stale} was not retired"
            assert rows[stale]["superseded_by"] == rows["Backup OK - 3"]["uuid"], (
                "the lineage must name the successor, or a hidden row has no "
                "way to explain itself")
            assert rows[stale]["wing_inbox_read_at"] is None, (
                "the reconciler marked a retired row READ — nobody read it, and "
                "that is the whole reason superseded_at exists")
        assert not rows["Backup OK - 3"]["superseded_at"], (
            "the newest row retired itself")


@pytest.mark.skipif(_php() is None, reason="php absent — the reconciler cannot run")
def test_it_never_runs_ahead_of_the_sender():
    """The authority is the emitter's own ACT. An emitter that has never sent a
    keyed row has not declared anything, and its backlog is not this tool's to
    retire — that judgement is the sender's and `supersede_key` is where it
    lives. A hardcoded table of 'repeating' emitters here would quietly take it
    back."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        db = _reconciler_db(tmp, [
            # gitleaks has NEVER declared: two findings are two secrets.
            ("Secret found in repo A", "gitleaks", "agent:gitleaks", None,
             "2026-08-01 01:00:00", None),
            ("Secret found in repo B", "gitleaks", "agent:gitleaks", None,
             "2026-08-02 01:00:00", None),
            # a row the OPERATOR already read, from a declared emitter
            ("Backup OK - old", "backup", "backup", None,
             "2026-08-01 01:00:00", "2026-08-01T09:00:00+00:00"),
            ("Backup OK - new", "backup", "backup", "backup-nightly-result",
             "2026-08-03 01:00:00", None),
        ])
        _run_reconciler(db, "--apply")
        rows = _state(db)
        assert not rows["Secret found in repo A"]["superseded_at"], (
            "retired a row from an emitter that never declared it repeats — "
            "two gitleaks findings are two different secrets")
        # DEFENDED TWICE, and that is worth knowing rather than discovering:
        # the sweep's SELECT excludes read rows, and the UPDATE's WHERE refuses
        # them again. Mutating EITHER alone leaves this assertion green —
        # verified 2026-08-24 — so it bites only when the property genuinely
        # goes, which is what it is for. Do not "simplify" one of the two away
        # on the grounds that a test still passes without it.
        assert not rows["Backup OK - old"]["superseded_at"], (
            "re-stamped a row the operator had already read; their decision "
            "must not be overwritten by the machine's")


@pytest.mark.skipif(_php() is None, reason="php absent — the reconciler cannot run")
def test_the_dry_run_is_the_default_and_writes_nothing():
    """The estate's destructive-op doctrine, and this tool hides rows."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        db = _reconciler_db(tmp, [
            ("Backup OK - 1", "backup", "backup", None, "2026-08-01 01:00:00", None),
            ("Backup OK - 2", "backup", "backup", "backup-nightly-result",
             "2026-08-03 01:00:00", None),
        ])
        out = _run_reconciler(db)                      # no --apply
        assert "WOULD RETIRE" in out.stdout, out.stdout[-400:]
        assert not _state(db)["Backup OK - 1"]["superseded_at"], (
            "the DEFAULT invocation wrote to the database")


def test_the_reconciler_asks_before_it_selects_the_column():
    """`superseded_at` arrives with the ALTER sweep. A host whose converge has
    not run must get a working reconciler, not a SQL error — and the tool must
    not silently do nothing either, which is why the guard is a PRAGMA and not
    a try/except swallow."""
    src = RECONCILER.read_text(encoding="utf-8")
    assert "PRAGMA table_info(notifications)" in src, (
        "the reconciler selects superseded_at without asking whether it exists")
    assert "$hasSupersede" in src


def test_the_repeaters_are_read_from_the_database_not_listed_here():
    """If this file ever grows a list of 'repeating' emitters, the declaration
    has two homes and the reconciler can retire rows for an emitter that never
    opted in."""
    src = RECONCILER.read_text(encoding="utf-8")
    fn = src[src.index("function declared_repeaters"):]
    fn = fn[:fn.index("\nfunction ", 10)]
    assert "SELECT" in fn and "supersede_key IS NOT NULL" in fn, (
        "declared_repeaters no longer derives the classes from what emitters "
        "have actually sent")
    # COMMENTS ARE NOT CODE. A `//` line naming a class to explain WHY it is
    # not hardcoded is exactly what this gate wants to encourage; matching it
    # as a violation is the detector-reads-prose defect (2026-08-25).
    code = "\n".join(ln for ln in src.splitlines()
                     if not ln.lstrip().startswith(("//", "*", "/*")))
    for hardcoded in EMITTERS.values():
        assert hardcoded not in code, (
            f"the reconciler hardcodes the class {hardcoded!r}; the emitter "
            "already declares it by sending it")


# ── a shared sender is not a class ─────────────────────────────────────────
#
# FOUND BY THE NIGHT OF 2026-08-24, which is the point of running one.
#
# `files/anatomy/scripts/nos-notify.sh` hardcoded `origin_plugin: os-resume` /
# `actor_id: agent:os-resume` for EVERY caller, and it is the shared sender for
# at least five: the os-update settle it is named for, the cortex corpus diff,
# the KEAP consolidator, the KEAP linter, and a readiness probe. Measured in the
# live ledger: 33 rows wearing a borrowed identity, six distinct message shapes
# under one name.
#
# `reconcile-inbox.php` keys the restatement CLASS on that identity. So the
# first genuine `os-resume-settled` emission would have retired thirty-five
# unrelated rows — S2-diff findings, KEAP batches, lint results — on the
# strength of a declaration that had nothing to do with them, silently, in a
# tool the operator now runs routinely. Simulated against a copy of the live
# database before the fix: 35 rows would have gone.
#
# Both halves are gated here. The reconciler REFUSES a shared identity and says
# so; the sender lets each caller carry its own.

def test_the_reconciler_refuses_a_shared_identity():
    src = RECONCILER.read_text(encoding="utf-8")
    assert "shape_count" in src, (
        "the shared-sender detection is gone. It is not inference — it counts "
        "DISTINCT message shapes under one (origin_plugin, actor_id), and no "
        "genuine restatement class produces more than one")
    fn = src[src.index("function shape_count"):]
    fn = fn[:fn.index("\n}") + 2]
    assert "return $row === false ? 99" in fn, (
        "an unreadable count must FAIL CLOSED — a shape_count that returns 0 "
        "or 1 on an error turns 'I could not tell' into 'safe to retire'")
    verdict = src[src.index("function verdict_restated"):]
    verdict = verdict[:verdict.index("\n}") + 2]
    assert "shared" in verdict and "'leave'" in verdict, (
        "verdict_restated no longer consults the shared-sender flag")


@pytest.mark.skipif(_php() is None, reason="php absent — the reconciler cannot run")
def test_a_borrowed_identity_is_refused_and_says_so():
    """EXERCISED. The refusal must also be VISIBLE: the first cut fired the
    guard and folded its `leave` into `unclassified`, discarding the reason —
    a tool declining to act and saying nothing, which is the defect this whole
    file is against."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        db = _reconciler_db(tmp, [
            # two DIFFERENT emitters wearing one identity, as nos-notify.sh
            # made them for a year
            ("S2 diff: 3 nights of agreement", "os-resume", "agent:os-resume",
             None, "2026-08-01 05:00:00", None),
            ("KEAP consolidator: data batch", "os-resume", "agent:os-resume",
             None, "2026-08-02 05:00:00", None),
            ("nOS macOS update settled (26.1)", "os-resume", "agent:os-resume",
             "os-resume-settled", "2026-08-03 05:00:00", None),
        ])
        out = _run_reconciler(db, "--apply")
        rows = _state(db)
        for borrowed in ("S2 diff: 3 nights of agreement", "KEAP consolidator: data batch"):
            assert rows[borrowed]["superseded_at"] is None, (
                f"{borrowed!r} was retired by an os-update settle message. They "
                "share an identity because one script sends for both; they are "
                "not the same class and one cannot restate the other")
        assert "shared sender" in out.stdout, (
            "the guard fired and said nothing. A refusal with no reason is "
            f"indistinguishable from having no rows to act on:\n{out.stdout[-400:]}")


def test_the_sender_lets_each_caller_name_itself():
    """The other half. Without this the reconciler refuses for ever and the
    inbox keeps filling with rows that cannot be classified."""
    src = (REPO / "files/anatomy/scripts/nos-notify.sh").read_text(encoding="utf-8")
    assert "NOS_NOTIFY_ORIGIN" in src and "NOS_NOTIFY_ACTOR" in src, (
        "nos-notify.sh hardcodes its callers' identity again. It sends for at "
        "least five different emitters; one name for all of them is what made "
        "a restatement class unattributable")
    assert 'origin_plugin:$op' in src.replace(" ", ""), (
        "the payload no longer carries the caller-supplied origin")
    assert 'os-resume' in src, (
        "the default must stay os-resume so the caller it was written for "
        "keeps working unchanged")


def test_every_caller_of_the_shared_sender_names_itself():
    """The half that stops the population regrowing.

    `nos-notify.sh` now ACCEPTS a caller identity, and that alone changes
    nothing: until each caller passes one, new rows keep arriving stamped
    `os-resume` and the reconciler keeps refusing them as a shared sender —
    correctly, and for ever.

    Measured 2026-08-25: five emitters shared one identity and 33 live rows
    wore it. Four of them are Pulse jobs declaring `NOS_NOTIFY_BIN` in a plugin
    manifest; this pins that declaring the BIN without the identity is
    incomplete.
    """
    import yaml as _yaml

    offenders: list[str] = []
    for manifest in sorted((REPO / "files/anatomy/plugins").glob("*/plugin.yml")):
        raw = manifest.read_text(encoding="utf-8")
        if "NOS_NOTIFY_BIN" not in raw:
            continue
        doc = _yaml.safe_load(raw) or {}
        for job in (doc.get("pulse", {}) or {}).get("jobs", []) or []:
            env = job.get("env") or {}
            if "NOS_NOTIFY_BIN" not in env:
                continue
            missing = [k for k in ("NOS_NOTIFY_ORIGIN", "NOS_NOTIFY_ACTOR") if k not in env]
            if missing:
                offenders.append(
                    f"{manifest.parent.name}/{job.get('name', '?')} declares "
                    f"NOS_NOTIFY_BIN without {', '.join(missing)}")

    assert not offenders, (
        "these jobs send through the shared notifier without saying who they "
        "are, so their rows land as `os-resume`:\n  " + "\n  ".join(offenders)
        + "\n(bin/reconcile-inbox.php keys a restatement class on "
          "(origin_plugin, actor_id); a borrowed identity makes the class "
          "unattributable and the rows unretirable)")
