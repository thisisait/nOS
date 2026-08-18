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
    src = TOOL.read_text(encoding="utf-8")
    assert "mode=ro" in src and "uri=True" in src, (
        "the wing.db connection is no longer opened read-only. The driver is "
        "what enforces this tool's central claim; without the flag the claim "
        "rests on nobody adding a write, which is not a guarantee."
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
