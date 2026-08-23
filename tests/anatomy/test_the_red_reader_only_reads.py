"""`tools/red-status.py` reports what is red and can never change it.

WHY THIS IS A GATE RATHER THAN A COMMENT. The tool exists because a nightly
job failed for two days in silence, and the obvious next thought — the one a
future contributor will have, reasonably — is "while it is looking, it could
just restart the job / re-stamp the component / mark the inbox read". That
addition is how this estate has acquired most of its expensive defects: a
success marker written by the code that attempted the work
(`docs/hidden_fees/`, and the standing rule in CLAUDE.md). A reader that could
also repair would eventually be asked to certify its own repair, and then the
red list would be reporting on itself.

So the read-only property is not a style preference, it is the whole reason
the output can be trusted. Two things are pinned:

1. The SQLite connection is opened `mode=ro` and the module contains no write
   verb. sqlite3 in read-only mode raises on any attempt, so the guarantee is
   enforced by the driver rather than by discipline.
2. An unreadable source is reported as UNKNOWN, never omitted. "No data" and
   "no problem" are the two readings this estate has most often confused — the
   STRICT health probe passing an empty stack as `0/0 ready` is the same shape
   (`docs/hidden_fees/08`), and it stayed green for weeks.

WHAT THIS GATE CANNOT DO: it does not check that the queries are correct, or
that the thresholds are wise. It checks that the tool cannot lie in the two
directions that would matter — by changing the estate, or by reading absence
as health.
"""

from __future__ import annotations

import ast
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
TOOL = REPO / "tools/red-status.py"

# Verbs that would turn the reader into a writer. `attach` is here because an
# ATTACHed database gets its own access mode and is the documented way around
# a read-only main connection.
WRITE_SQL = ("insert ", "update ", "delete ", "drop ", "create ", "alter ", "attach ")


def test_the_tool_this_gate_describes_exists():
    """Positive control — a renamed tool makes every check below vacuous."""
    assert TOOL.is_file(), "tools/red-status.py is gone"
    assert TOOL.stat().st_mode & 0o111, "tools/red-status.py is not executable"


def test_the_connection_is_opened_read_only():
    """The claim is unchanged; on 2026-08-20 its enforcement MOVED.

    `mode=ro` alone dies with "unable to open database file" whenever no writer
    holds wing.db's WAL sidecars — which, after a converge restarts Wing, is
    most of the time. The open therefore lives in `tools/_ledger_open.py`, which
    still tries read-only FIRST and falls back only to an immutable snapshot,
    never to a writable handle. This gate follows it there rather than passing
    because the old string is still lying around somewhere in the file.
    """
    opener = TOOL.parent / "_ledger_open.py"
    assert opener.is_file(), f"{opener.name} is gone; the shared opener is the enforcement"
    osrc = opener.read_text(encoding="utf-8")
    assert "mode=ro" in osrc and "uri=True" in osrc, (
        "the shared opener no longer opens read-only. Without the flag the "
        "claim rests on nobody adding a write, which is not a guarantee."
    )
    assert "mode=rw" not in "\n".join(
        ln for ln in osrc.splitlines() if "sqlite3.connect" in ln or "?mode=" in ln
    ), "the opener reaches for a writable connection"

    src = TOOL.read_text(encoding="utf-8")
    assert "_ledger_open" in src, (
        "red-status no longer routes through the shared opener; a bare "
        "sqlite3.connect here is one converge away from a traceback"
    )


def test_every_sql_the_tool_executes_is_a_read():
    """Scoped to what is handed to `.execute()`, not to every string in the
    file: the module's own prose explains why it does not delete or update
    anything, and a whole-file substring search would fail on that sentence —
    a gate that its own documentation trips is a gate people delete."""
    tree = ast.parse(TOOL.read_text(encoding="utf-8"))
    executed: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "execute"):
            continue
        assert node.args, "an .execute() call with no literal SQL to inspect"
        arg = node.args[0]
        assert isinstance(arg, ast.Constant) and isinstance(arg.value, str), (
            "red-status.py now builds SQL dynamically. The gate can no longer "
            "read what it runs, so it can no longer promise the run is a read."
        )
        executed.append(arg.value)

    assert executed, "no .execute() calls found — this gate has stopped seeing the queries"
    for sql in executed:
        lowered = " ".join(sql.lower().split())
        assert lowered.startswith("select"), f"a query does not start with SELECT: {sql[:70]!r}"
        for verb in WRITE_SQL:
            assert verb not in lowered, (
                f"executed SQL contains {verb.strip()!r}. This tool reports; "
                "repair belongs to the playbook and the operator."
            )


def test_it_writes_nothing_to_the_filesystem():
    src = TOOL.read_text(encoding="utf-8").replace("sys.stdout.write(", "")
    for verb in ("open(", ".write(", ".unlink(", ".mkdir(", ".write_text("):
        assert verb not in src, (
            f"red-status.py now calls {verb} — it writes to the filesystem. "
            "Its only output is stdout."
        )


def test_a_missing_source_is_reported_not_skipped(tmp_path):
    """EXERCISED, not grepped. Point HOME at an empty directory so wing.db and
    backup-status.json genuinely do not exist, and check the tool says so. A
    version of this test that only searched the source for the phrase would
    keep passing after someone moved the branch that emits it."""
    import json
    import os

    env = dict(os.environ, HOME=str(tmp_path))
    proc = subprocess.run(
        [sys.executable, str(TOOL), "--json"],
        capture_output=True, text=True, cwd=REPO, env=env, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr[-800:]
    report = json.loads(proc.stdout)

    assert report["sources_missing"], (
        "with HOME empty, wing.db and backup-status.json cannot exist, yet the "
        "tool reported no missing sources — absence is being read as health."
    )
    unknown = [line for line in report["reds"] if "UNKNOWN not green" in line]
    assert len(unknown) == len(report["sources_missing"]), (
        "an unreadable source did not produce a red line. A short, calm, "
        "entirely green list on an estate the tool could not read is the exact "
        "failure this estate has paid for most often."
    )


def test_job_lateness_is_measured_against_the_schedule():
    """The first version used a flat two-day threshold and reported two WEEKLY
    jobs as red on the day it shipped — both had fired on Sunday exactly as
    scheduled. A red list that cries about healthy jobs is a red list nobody
    finishes reading, which is precisely the failure this tool exists to fix.
    Lateness must come from `next_fire_at`, which the estate already computes,
    and paused jobs must be excluded — parked is not red."""
    src = TOOL.read_text(encoding="utf-8")
    assert "next_fire_at" in src, (
        "job lateness no longer reads next_fire_at. Any constant threshold "
        "mistakes a longer period for a stopped job."
    )
    assert "paused = 0" in src, (
        "paused jobs are no longer excluded from the overdue check. A pause is "
        "an operator's deliberate act and carries a reason; it is not red."
    )


def test_it_runs_and_exits_zero_even_when_red():
    """Exit 0 is deliberate and documented: this reports, it does not judge.
    A reader that went red on bad news would be a gate, and a gate on a
    calendar goes red on publication day rather than on a defect."""
    proc = subprocess.run(
        [sys.executable, str(TOOL), "--json"],
        capture_output=True, text=True, cwd=REPO, timeout=60,
    )
    assert proc.returncode == 0, (
        f"red-status.py exited {proc.returncode}; it must exit 0 whatever it "
        f"finds. stderr:\n{proc.stderr[-800:]}"
    )
    import json

    report = json.loads(proc.stdout)
    assert "red_count" in report and "reds" in report
    assert report["red_count"] == len(report["reds"])


def test_a_declared_findings_exit_code_is_not_a_failure(tmp_path, monkeypatch):
    """A job may declare which non-zero codes mean "I found something".

    MEASURED 2026-08-20: `discovery:contradiction-scan` declares
    `findings_exit_codes = [1]` and exited 1 having done exactly its job
    ("filed 1 new roadmap row(s)"). This reader did not know the column
    existed and called it failing — while `bin/reconcile-inbox.php`, reading
    the same two tables, called it green. Two readers disagreeing about one
    fact is worse than either being wrong alone, and a reader that cries wolf
    is one the operator learns to skim.
    """
    import importlib.util
    import sqlite3

    db = tmp_path / "wing.db"
    with sqlite3.connect(db) as seed:
        seed.execute("CREATE TABLE pulse_runs (job_id TEXT, fired_at TEXT, "
                     "exit_code INT, duration_ms INT, stdout_tail TEXT)")
        seed.execute("CREATE TABLE pulse_jobs (id TEXT, findings_exit_codes TEXT)")
        seed.executemany("INSERT INTO pulse_runs VALUES (?,?,?,?,?)", [
            ("finder:scan",  "2026-08-20T06:44:00+00:00", 1, 10, "filed 1 new row"),
            ("broken:job",   "2026-08-20T06:44:00+00:00", 1, 10, "ERROR: it broke"),
            ("undeclared:j", "2026-08-20T06:44:00+00:00", 1, 10, "ERROR: no decl"),
        ])
        seed.executemany("INSERT INTO pulse_jobs VALUES (?,?)", [
            ("finder:scan", "[1]"),
            ("broken:job", "[3]"),
            ("undeclared:j", None),
        ])

    spec = importlib.util.spec_from_file_location("_red_findings", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        named = {j["job"] for j in mod.failing_jobs(conn)}
    finally:
        conn.close()

    assert "finder:scan" not in named, (
        "a job that exited with its OWN declared findings code was reported as "
        "failing; that is the cry-wolf shape this file exists to prevent"
    )
    assert "broken:job" in named, (
        "exit 1 against a declaration of [3] is a real failure and must be "
        "reported — otherwise the fix silences genuine breakage"
    )
    assert "undeclared:j" in named, (
        "a job that declares nothing must still be reported on a non-zero exit"
    )


def test_an_unparseable_findings_declaration_still_reports(tmp_path):
    """Absence of a readable declaration must not read as 'this is fine'."""
    import importlib.util
    import sqlite3

    db = tmp_path / "wing.db"
    with sqlite3.connect(db) as seed:
        seed.execute("CREATE TABLE pulse_runs (job_id TEXT, fired_at TEXT, "
                     "exit_code INT, duration_ms INT, stdout_tail TEXT)")
        seed.execute("CREATE TABLE pulse_jobs (id TEXT, findings_exit_codes TEXT)")
        seed.execute("INSERT INTO pulse_runs VALUES "
                     "('j','2026-08-20T06:44:00+00:00',1,10,'ERROR: x')")
        seed.execute("INSERT INTO pulse_jobs VALUES ('j','not json at all')")

    spec = importlib.util.spec_from_file_location("_red_unparseable", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        assert {j["job"] for j in mod.failing_jobs(conn)} == {"j"}
    finally:
        conn.close()



# ── The inbox line reports STATE, not unread count (2026-08-23) ──────────────
#
# This reader exists because "a notification is an EVENT and red is a STATE".
# Its own inbox line broke that rule: it counted UNREAD CRITICAL/HIGH, and four
# of the loudest were `security-drift` rows that were TRUE when sent and false
# within the day. On 2026-08-22 the estate really did have 11 pending HIGH; they
# were closed that afternoon. So the state reader was generating a red from a
# stale event — the exact thing it was built to stop.
#
# It now re-decides a notification's own claim where the emitter left a
# measurable one. What must never happen is the reverse error: a claim it
# cannot check being reported as CLEARED.

def test_an_uncheckable_notification_is_unknown_and_never_cleared():
    """`_still_holds` has three answers and the middle one is load-bearing."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("red_status", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    class Row(dict):
        def __getitem__(self, k):
            return self.get(k)

    # No metadata at all — the librarian's failure notification is like this.
    assert mod._still_holds(Row(origin_plugin="librarian", origin_agent=None,
                               metadata_json=None)) is None
    # Metadata present but from a class with no re-check rule.
    assert mod._still_holds(Row(origin_plugin="os-resume", origin_agent=None,
                                metadata_json='{"nights": "14"}')) is None
    # Malformed metadata must not read as cleared either.
    assert mod._still_holds(Row(origin_plugin="security-drift", origin_agent=None,
                                metadata_json="{not json")) is None


def test_a_drift_claim_is_decided_against_the_queue_in_both_directions():
    import importlib.util

    spec = importlib.util.spec_from_file_location("red_status", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    class Row(dict):
        def __getitem__(self, k):
            return self.get(k)

    row = Row(origin_plugin="security-drift", origin_agent=None,
              metadata_json='{"pending_critical": "1", "pending_high": "11"}')

    # The estate has at least as many as were claimed -> the alarm still holds.
    mod._queue_pending = lambda: {"critical": 1, "high": 2}
    assert mod._still_holds(row) is True
    # Fewer than claimed -> the specific alarm was answered.
    mod._queue_pending = lambda: {"critical": 0, "high": 2}
    assert mod._still_holds(row) is False
    # The queue itself unreadable -> UNKNOWN, never cleared. This is the branch
    # that would quietly drain the red list if it returned False.
    mod._queue_pending = lambda: None
    assert mod._still_holds(row) is None


def test_the_inbox_line_separates_superseded_from_unverifiable():
    """Both numbers must reach the operator. Collapsing `unknown` into
    `still true` overstates; collapsing it into `stale` hides."""
    src = TOOL.read_text()
    body = src[src.index("def reds("):]
    for phrase in ("re-checked and still true", "no re-checkable claim", "true when sent"):
        assert phrase in body, (
            f"the inbox red no longer distinguishes its three populations "
            f"({phrase!r} is gone) — the first version said 9 'still hold' when "
            "all nine were merely unverifiable")
