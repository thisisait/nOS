"""A skip that cannot say why is a verdict nobody can act on.

FOUND BY THE LOOP, ON ITS FIRST REAL TURN (2026-08-03). The baseline `fast` set
sealed:

    result:   indeterminate
    outcomes: {"ansible-lint": "indeterminate", "genome-codegen": "pass"}
    reason:   "ansible-lint: "

The engine did the hard part right — a judge that did not run is INDETERMINATE,
never PASS — and then lost the one field that made it actionable. `judges.
_executable_present` had computed the exact sentence (`executable 'ansible-lint'
not found on PATH`), `_skipped` carried it on the JudgeRun, and
`finish_judge_run` did not persist it: `loop_judge_runs` had no `reason` column.
The row was rehydrated for aggregation with an empty reason, so the sealed
verdict knew WHICH judge had not run and could not say WHY.

The cause, once the reason survived: `ansible-lint` exists only at
`~/.pyenv/shims/ansible-lint`, and launchd hands the Bone daemon a PATH that had
the venv and Homebrew but no shims. One judge of five was unreachable in
production and reachable from every harness — the same shape as the repo-root
defect found hours earlier, and as `resolve_openssl` in `backup.sh`, which
carries a comment about this exact launchd behaviour.

WHY THIS IS ITS OWN GATE rather than a line in the ledger tests: the ledger
suite proves that a row round-trips, and it round-tripped perfectly — the field
simply was not in the schema, so nothing was lost as far as any test could see.
An absent column is invisible to tests written against the columns that exist.
"""

from __future__ import annotations

import importlib
import plistlib
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
BONE = REPO / "files/anatomy/bone"
PLIST = REPO / "roles/pazny.bone/templates/bone.plist.j2"


@pytest.fixture(scope="module")
def mods():
    sys.path.insert(0, str(BONE))
    try:
        yield {
            "ledger": importlib.import_module("ledger"),
            "judges": importlib.import_module("judges"),
        }
    finally:
        sys.path.remove(str(BONE))


def test_the_run_table_can_hold_a_reason(mods):
    """The column. Absent, every skip is anonymous."""
    ddl = mods["ledger"]._DDL
    runs = ddl[ddl.index("CREATE TABLE IF NOT EXISTS loop_judge_runs"):]
    runs = runs[: runs.index(");")]
    assert re.search(r"^\s*reason\s+TEXT", runs, re.M), (
        "loop_judge_runs has no `reason` column again. The JudgeRun carries one; "
        "without somewhere to put it the verdict reads `<judge>: ` and an "
        "operator cannot tell a missing binary from a busy lock from a crash."
    )
    assert ("loop_judge_runs", "reason", "TEXT") in mods["ledger"]._ADDED_COLUMNS, (
        "the column is in the CREATE but not in the idempotent ALTER sweep, so "
        "every host that already has a ledger keeps the anonymous version"
    )


def test_the_writer_persists_it(mods):
    """A column nothing writes to is the same silence with extra steps."""
    src = (BONE / "ledger.py").read_text(encoding="utf-8")
    fn = src[src.index("def finish_judge_run"):]
    fn = fn[: fn.index("\n    def ")]
    assert "reason=?" in fn, (
        "finish_judge_run does not write the reason. It is computed in "
        "judges._executable_present and thrown away at the database boundary — "
        "which is exactly how it was lost the first time."
    )


def test_the_reader_hands_it_back(mods):
    """...and a value written but not read back is still unusable."""
    src = (BONE / "ledger.py").read_text(encoding="utf-8")
    fn = src[src.index("def _as_judge_run"):]
    fn = fn[: fn.index("\n\n\n")]
    assert "reason" in fn, (
        "_as_judge_run rehydrates a run without its reason, so aggregation "
        "reasons over a blank again"
    )


def test_the_judge_binary_is_reachable_from_the_daemon():
    """The cause, pinned where it actually lives: the launchd PATH.

    Not asserted against the running host — this is an offline gate — but
    against the template that produces it. A PATH without the shim directory is
    a PATH in which one of the five judges cannot be found, and the loop then
    cannot reach a verdict no matter how correct the rest of it is.
    """
    text = PLIST.read_text(encoding="utf-8")
    m = re.search(r"<key>PATH</key>\s*(?:\{#.*?#\}\s*)?<string>([^<]*)</string>", text, re.S)
    assert m, "the PATH entry is no longer recognisable in bone.plist.j2"
    path = m.group(1)
    assert ".pyenv/shims" in path, (
        "the pyenv shim directory left Bone's PATH. `ansible-lint` (and pytest) "
        "exist only as shims on this estate; without it the judge is SKIPPED, "
        "the set aggregates to INDETERMINATE, and no proposal can ever be "
        "accepted or rejected — the loop runs and decides nothing."
    )
    # Ordering matters: the engine's own venv must still win for `python3`,
    # so a judge spawned by Bone runs under the interpreter Bone was built with
    # rather than whatever the shim resolves to today.
    assert path.index("bone") < path.index(".pyenv/shims") if "bone" in path else True, (
        "the shim directory now precedes Bone's venv, so `python3` resolves to "
        "the shim instead of the engine's own interpreter"
    )
