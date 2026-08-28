"""Anatomy gate — 'satisfied' is a gate run's verdict, never a claim.

The outcome loop used to grade itself: with no `model.grader` declared, the
Grader was handed the proposer's own client, so the judge and the proposer
were one identity (arXiv:2510.16657 is why that is not a cheap approximation
of a second opinion). The satisfied row it wrote had nothing behind it.

Two artifacts close that, and this file reads both rather than the prose about
them:

  * the DB refuses `grader_result='satisfied'` without a `gate_run_id` — the
    constraint lives in the schema a converge applies, so no writer can opt
    out of it, including a future one nobody has written yet;
  * `Grader::forUri(null, …)` returns null and never touches the resolver, so
    "no grader declared" means no grader CALL, not a silent fallback.
"""

from __future__ import annotations

import json
import pathlib
import shutil
import sqlite3
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
WING = REPO / "files" / "anatomy" / "wing"
AUTOLOAD = WING / "vendor" / "autoload.php"

needs_php = pytest.mark.skipif(shutil.which("php") is None, reason="php not on PATH")


def _fresh_db(tmp_path: pathlib.Path) -> pathlib.Path:
    """Build via the REAL init-db.php: the triggers are created there, after
    the ALTER sweep that adds gate_run_id. Applying schema-extensions.sql
    alone would give a DB with the column and none of the constraint."""
    r = subprocess.run(
        ["php", str(WING / "bin" / "init-db.php"), f"--data-dir={tmp_path}"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, f"init-db failed building test DB: {r.stderr}"
    return tmp_path / "wing.db"


def _row(**over) -> dict:
    row = {
        "session_uuid": "s-1",
        "iteration": 0,
        "grader_result": "satisfied",
        "grader_feedback": "looks great to me",
        "grader_model": "anthropic-claude-sonnet-4-5",
        "gate_run_id": None,
    }
    row.update(over)
    return row


def _insert(con: sqlite3.Connection, row: dict) -> None:
    cols = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    con.execute(f"INSERT INTO agent_iterations ({cols}) VALUES ({marks})", tuple(row.values()))
    con.commit()


@needs_php
def test_the_db_refuses_a_satisfied_row_with_no_gate_run(tmp_path):
    """The bare insert, attempted. A gate that only read the DDL would pass
    against a DB where the trigger was never created — which is the state
    every pre-existing wing.db is in until init-db.php runs."""
    con = sqlite3.connect(_fresh_db(tmp_path))
    with pytest.raises(sqlite3.Error) as exc:
        _insert(con, _row())
    assert "gate_run_id" in str(exc.value)
    con.rollback()

    # Whitespace is the same claim with a value in the column. Tabs and
    # newlines are here because SQLite's ONE-ARG TRIM() strips ASCII space and
    # nothing else — "\t\n" wrote the row until 2026-08-29.
    for blank in ("   ", "\t\n", "\r", " \t "):
        with pytest.raises(sqlite3.Error):
            _insert(con, _row(gate_run_id=blank))
        con.rollback()

    # Promotion after the fact is the same hole with an UPDATE in it.
    _insert(con, _row(grader_result="needs_revision"))
    with pytest.raises(sqlite3.Error):
        con.execute("UPDATE agent_iterations SET grader_result='satisfied' WHERE iteration=0")
        con.commit()
    con.rollback()
    con.close()


@needs_php
def test_a_gate_run_id_is_what_makes_satisfied_writable(tmp_path):
    """The control: the constraint blocks the unbacked row, not every row."""
    con = sqlite3.connect(_fresh_db(tmp_path))
    _insert(con, _row(gate_run_id="a" * 64))
    got = con.execute(
        "SELECT grader_result, gate_run_id FROM agent_iterations"
    ).fetchone()
    assert got == ("satisfied", "a" * 64)
    con.close()


@needs_php
def test_the_session_records_that_an_output_was_repaired(tmp_path):
    """output_repaired defaults to 0 — absent is not 'clean', it is 'nothing
    repaired', and the flag has to exist before anything can set it."""
    con = sqlite3.connect(_fresh_db(tmp_path))
    cols = {r[1]: r for r in con.execute("PRAGMA table_info(agent_sessions)")}
    assert "output_repaired" in cols, "agent_sessions cannot record a repair"
    assert cols["output_repaired"][4] == "0", "the default is not 'nothing repaired'"
    con.close()


@needs_php
@pytest.mark.skipif(not AUTOLOAD.exists(), reason="wing vendor tree not installed")
def test_no_grader_declared_means_no_grader_call(tmp_path):
    """The deleted fallback, asserted on behaviour: the resolver THROWS, so a
    Grader constructed on the null path cannot be silent about it."""
    probe = tmp_path / "probe.php"
    probe.write_text(
        "<?php\n"
        f"require {str(AUTOLOAD)!r};\n"
        "use App\\AgentKit\\Outcome\\Grader;\n"
        "$boom = function (string $uri) { throw new RuntimeException('resolver called for ' . $uri); };\n"
        "$out = [];\n"
        "try { $out['none'] = Grader::forUri(null, $boom); }\n"
        "catch (Throwable $e) { $out['none'] = 'THREW: ' . $e->getMessage(); }\n"
        "try { Grader::forUri('anthropic-claude-haiku-4-5', $boom); $out['declared'] = 'no-call'; }\n"
        "catch (Throwable $e) { $out['declared'] = 'resolved'; }\n"
        "echo json_encode($out);\n",
        encoding="utf-8",
    )
    r = subprocess.run(["php", str(probe)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    got = json.loads(r.stdout)
    assert got["none"] is None, (
        "an agent with no model.grader still gets a Grader — the proposer is "
        f"grading itself again: {got['none']!r}"
    )
    assert got["declared"] == "resolved", (
        "a declared grader never reaches the client resolver, so it is not "
        "actually a second model"
    )


AGENT_YML = """name: probe
version: 1
description: a probe agent authored by the anatomy gate, never run
model:
  primary: claude-sonnet
{grader}audit:
  capability_scopes: [wing.read]
  pii_classification: none
outcomes:
{outcomes}"""


def _load(tmp_path: pathlib.Path, *, grader: str = "", outcomes: str, repo_root=REPO) -> str:
    """Load a probe agent through the REAL AgentLoader; return '' or the refusal."""
    agents = tmp_path / "agents" / "probe"
    agents.mkdir(parents=True, exist_ok=True)
    (agents / "rubric.md").write_text("# rubric\n", encoding="utf-8")
    (agents / "agent.yml").write_text(
        AGENT_YML.format(grader=grader, outcomes=outcomes), encoding="utf-8"
    )
    probe = tmp_path / "load.php"
    probe.write_text(
        "<?php\n"
        f"require {str(AUTOLOAD)!r};\n"
        # ToolSpec lives inside Agent.php, which PSR-4 cannot find by its own name.
        f"require {str(WING / 'app' / 'AgentKit' / 'Agent.php')!r};\n"
        "use App\\AgentKit\\AgentLoader;\n"
        f"putenv('NOS_REPO_ROOT=' . {str(repo_root)!r});\n"
        f"$l = new AgentLoader({str(agents.parent)!r});\n"
        "try { $a = $l->load('probe'); echo json_encode(['gateset' => $a->gateset]); }\n"
        "catch (Throwable $e) { echo json_encode(['refused' => $e->getMessage()]); }\n",
        encoding="utf-8",
    )
    r = subprocess.run(["php", str(probe)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    got = json.loads(r.stdout)
    return got.get("refused", "")


@needs_php
@pytest.mark.skipif(not AUTOLOAD.exists(), reason="wing vendor tree not installed")
def test_the_loader_refuses_an_outcome_with_no_oracle(tmp_path):
    """An outcome loop needs something to ask that is not the model."""
    assert "gateset is required" in _load(tmp_path, outcomes="  rubric_path: rubric.md\n")
    assert "not in state/judge-sets.yml" in _load(tmp_path, outcomes="  gateset: nonesuch\n")
    # The control: a real set loads, and the rubric is optional beside it.
    assert _load(tmp_path, outcomes="  gateset: fast\n") == ""


@needs_php
@pytest.mark.skipif(not AUTOLOAD.exists(), reason="wing vendor tree not installed")
def test_the_loader_refuses_a_grader_that_is_the_proposer(tmp_path):
    """Same model on both sides is the arrangement arXiv:2510.16657 measures
    agreeing with itself — refused, not tolerated with a warning."""
    refusal = _load(
        tmp_path, grader="  grader: claude-sonnet\n", outcomes="  gateset: fast\n"
    )
    assert "must differ from model.primary" in refusal


@needs_php
@pytest.mark.skipif(not AUTOLOAD.exists(), reason="wing vendor tree not installed")
def test_an_unreadable_registry_is_a_refusal_not_an_empty_allowlist(tmp_path):
    """Absence is UNKNOWN. A registry nobody can read must not resolve to
    'no rules', which is how an unrunnable gate set gets accepted at the door
    and discovered three hours into a session."""
    refusal = _load(tmp_path, outcomes="  gateset: fast\n", repo_root=tmp_path / "nowhere")
    assert "judge-sets.yml not readable" in refusal
