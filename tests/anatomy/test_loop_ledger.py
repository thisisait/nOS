"""Anatomy gate — the agentic-loop ledger, and the one thing it must guarantee.

Contract: docs/idea/11-agentic-loop-contract.md (§2.4, §3, §4, §5a).
Subject:  files/anatomy/bone/ledger.py

THE REQUIREMENT THAT MATTERS: **a proposer must be structurally unable to write
a verdict.** In a self-improvement loop the verdict IS the reward signal for the
next modification, so a proposer that can influence its verdict does not merely
lie — it optimises against the lie.

This file is therefore built around the ADVERSARIAL case, not the happy path.
Every layer of §3.3's claim is attacked here, in the order the contract makes
it, and the last one is attacked to show it FAILS (offline tampering is
detected, not prevented — claiming otherwise would be decoration):

  layer 1  no API surface accepts a result  → test_seal_verdict_takes_no_result_parameter
                                              test_proposer_has_no_method_that_writes_a_verdict
  layer 2  the connection refuses it        → test_ADVERSARIAL_*  (four of them)
  layer 3  the schema refuses it            → test_ADVERSARIAL_schema_refuses_a_non_engine_actor
  layer 4  WORM refuses edits               → test_ADVERSARIAL_worm_refuses_*
  layer 5  the chain makes it EVIDENT       → test_ADVERSARIAL_offline_forgery_is_detected_not_prevented

Constraint B (a step may not record its own success) is attacked separately:
the run row exists before any outcome does, the outcome is derived from raw
process facts, a killed run can never become PASS, and a finished run is
immutable.

CI-safe: pure sqlite3 in a tmp dir. No live estate, no subprocess, no network.
"""

from __future__ import annotations

import ast
import inspect
import json
import re
import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
BONE = REPO / "files/anatomy/bone"
if str(BONE) not in sys.path:
    sys.path.insert(0, str(BONE))

import judges  # noqa: E402  — the derivation site the ledger persists for
import ledger  # noqa: E402  — after sys.path setup, same pattern as tests/callback/


# ── Judge specs mirroring the five REAL judges (§2.2) ─────────────────────
# argv[0] is `python3` so `judges._executable_present` is satisfied; the
# process itself is always faked, so nothing on this machine is actually run.
# These are `judges.JudgeSpec` — the ledger deliberately has no spec type of
# its own (constraint H: one derivation site, not two).

def spec(name: str, **kw) -> judges.JudgeSpec:
    return judges.JudgeSpec(name=name, argv=("python3", "--version"), **kw)


LINT = spec("ansible-lint", adapter="exit_zero", pass_exit=(0,), fail_exit=(2,),
            min_work=1400, work_regex=r"(\d+) files processed")
CODEGEN = spec("genome-codegen", adapter="exit_zero", pass_exit=(0,), fail_exit=(1,),
               min_work=2, work_regex=r"genome artifacts current \((\d+) checked\)")
SMOKE = spec("nos-smoke", adapter="exit_count", min_work=1, work_regex=r"(\d+) entries")
PYTEST_J = spec("pytest-anatomy", adapter="pytest_summary", min_work=1)
CORPUS = spec("cortex-corpus-diff", adapter="json_field", json_field="agrees",
              min_work=1, work_json_field="nodes")

LINT_OK = "1500 files processed"                       # >= min_work
CODEGEN_OK = "genome artifacts current (2 checked)"
CODEGEN_STALE = "STALE generated artifacts: files/anatomy/module_utils/nos_entity.py"


#: The sha the fake sandbox reports. `judges` reads this out of a real git
#: worktree in production; here it is a constant so these tests stay hermetic.
TREE = "a" * 40

#: The gate sets these tests seal, and their membership — the shape
#: `judges.load_registry()` returns, injected at ledger construction so the
#: suite does not depend on the committed registry's current contents.
TEST_REGISTRY = judges.Registry(
    judges={},
    gate_sets={
        "fast": judges.GateSetSpec(name="fast", judges=("ansible-lint", "genome-codegen")),
        "solo": judges.GateSetSpec(name="solo", judges=("ansible-lint",)),
        "probe": judges.GateSetSpec(name="probe", judges=()),
    },
)

#: `{weakness_id: evidence_sha}` as the weakness READER would return it. The
#: ledger looks the sha up here; nothing in a proposal can supply one.
WEAKNESS_INDEX = {"hidden-fee:08": "sha-08", "REM-137": "sha-137"}


def derive(judge: judges.JudgeSpec, exit_code, stdout: str = "", stderr: str = "",
           tree_sha: str = TREE) -> judges.JudgeRun:
    """Drive the REAL judge pipeline with only the subprocess faked.

    `run_gate_set`'s `spawn` seam is the sibling module's own injection point,
    so the adapters, the work parser and the §2.4 ratchet all execute exactly
    as they would in production — the bytes on the pipe are simply supplied.
    The sandbox is faked too (this file makes no subprocess at all); it hands
    back a tree sha exactly as the real one does, because there is no seam that
    yields a tree with no identity.
    """
    reg = judges.Registry(
        judges={judge.name: judge},
        gate_sets={"probe": judges.GateSetSpec(name="probe", judges=(judge.name,))})
    verdict = judges.run_gate_set(
        "probe", registry=reg, repo_root=REPO, probe=lambda r: True,
        sandbox_factory=lambda root: (root, tree_sha, lambda: None),
        spawn=lambda argv, cwd, t: judges.Completed(
            exit_code=exit_code, stdout=stdout, stderr=stderr))
    return verdict.runs[0]


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """A tmp wing.db. `clients/wing.py::_open` requires the file to exist."""
    path = tmp_path / "wing.db"
    sqlite3.connect(str(path)).close()
    monkeypatch.setenv("WING_DB_PATH", str(path))
    monkeypatch.setenv("WING_EVENTS_HMAC_SECRET", "loop-ledger-test-secret")
    # No repo resolvable → `_patch_state_at_head` answers "unknown" and the
    # passed-awaiting-act refusal behaves as before. A developer shell that
    # happens to export PLAYBOOK_DIR must not flip these tests' verdicts.
    monkeypatch.delenv("NOS_LOOP_REPO_ROOT", raising=False)
    monkeypatch.delenv("PLAYBOOK_DIR", raising=False)
    return path


def _open(role: str):
    return ledger.open_ledger(role, registry=TEST_REGISTRY, weakness_index=WEAKNESS_INDEX)


@pytest.fixture()
def proposer(db):
    led = _open("proposer")
    yield led
    led.close()


@pytest.fixture()
def evaluator(db):
    led = _open("evaluator")
    yield led
    led.close()


def raw(db) -> sqlite3.Connection:
    """A connection with NO authorizer — the "stray SQL client" of §3.3(2), and
    the shell-holding attacker of §3.3(3)."""
    c = sqlite3.connect(str(db))
    c.row_factory = sqlite3.Row
    return c


DEFAULT_TARGET = "roles/pazny.gitea/defaults/main.yml"


def mkdiff(new: str = "b", path: str = DEFAULT_TARGET, at: int = 1) -> str:
    """A minimal diff whose headers NAME the path it claims to edit.

    §5 now reads the artifact in both directions — a diff that touches an
    undeclared path is refused, and so is a declared path the diff never
    touches — so a headerless hunk (this file's old fixture) no longer
    represents a valid proposal.
    """
    return f"--- a/{path}\n+++ b/{path}\n@@ -{at} +{at} @@\n-a\n+{new}\n"


def propose(led, **over):
    kw = dict(weakness_id="hidden-fee:08", target_paths=[DEFAULT_TARGET],
              intent_class="version-pin-bump", gate_set="fast", tree_sha="a" * 40,
              proposer_id="agent:remediator", proposer_model="anthropic-claude-opus-5")
    kw.update(over)
    # diff_text is REQUIRED now; default to a diff that matches the declaration
    # so each test states only what it is about.
    if "diff_text" not in kw:
        kw["diff_text"] = "".join(mkdiff(path=p) for p in kw["target_paths"])
    return led.record_proposal(**kw)


def judge_set(ev, runs, *, gate_set=None, proposal_uuid=None, tree_sha=TREE):
    """Drive a full set: begin → finish → seal. `runs` is [(spec, exit, stdout)].

    `gate_set` defaults to an ad-hoc set whose declared membership IS the judges
    being driven — because `seal_verdict` reads membership from the registry now
    and refuses to be told what it should have expected.
    """
    names = tuple(j.name for j, _, _ in runs)
    if gate_set is None:
        gate_set = "gs:" + ",".join(names)
        TEST_REGISTRY.gate_sets[gate_set] = judges.GateSetSpec(  # type: ignore[index]
            name=gate_set, judges=names)
    for judge, code, out in runs:
        run = derive(judge, code, out, tree_sha=tree_sha)
        u = ev.begin_judge_run(gate_set=gate_set, judge_name=judge.name,
                               argv=run.argv, proposal_uuid=proposal_uuid)
        ev.finish_judge_run(u, run=run)
    return ev.seal_verdict(gate_set=gate_set, proposal_uuid=proposal_uuid)


# ══════════════════════════════════════════════════════════════════════════
# LAYER 1 — no API surface accepts a result
# ══════════════════════════════════════════════════════════════════════════

def test_seal_verdict_takes_no_result_parameter():
    """You cannot forge a value you are never asked to supply (§3.1).

    Goes red the moment someone adds `result=` (or `status=`, or `passed=`) to
    the only verdict writer — which is precisely how the parent's deleted
    `POST /v1/verdicts` would creep back in.
    """
    params = set(inspect.signature(ledger.EvaluatorLedger.seal_verdict).parameters)
    forbidden = {"result", "verdict", "status", "outcome", "passed", "ok", "score"}
    assert not (params & forbidden), (
        f"seal_verdict accepts a caller-supplied result: {sorted(params & forbidden)}. "
        "The result must be derived from persisted judge-run rows.")


def test_seal_verdict_does_not_let_its_caller_choose_the_evidence():
    """The half "no result parameter" does not cover, and the half that broke.

    Selection IS forgery. A caller that names WHICH runs count can assemble a
    PASS out of a green subset while a FAIL for the same proposal sits in
    `loop_judge_runs`; a caller that supplies `expected_judges` can make the
    missing-judge guard vacuous by passing `[]`; a caller that types `tree_sha`
    can seal a verdict about a tree nothing was judged on. All three were
    reachable, and all three are parameters, so this gate is a signature gate.
    """
    params = set(inspect.signature(ledger.EvaluatorLedger.seal_verdict).parameters)
    forbidden = {"run_uuids", "runs", "evidence", "expected_judges", "judges",
                 "tree_sha", "registry"}
    assert not (params & forbidden), (
        f"seal_verdict lets its caller select its own evidence: "
        f"{sorted(params & forbidden)}. Membership comes from the registry, the "
        f"runs come from the ledger, the tree comes off the runs.")
    assert params == {"self", "gate_set", "proposal_uuid"}, sorted(params)


def test_proposer_has_no_method_that_writes_a_verdict():
    """The proposer's PUBLIC surface is read-or-propose, exhaustively.

    The `list_*` trio landed 2026-08-06 (the run screen's read surface —
    explicit column lists, `diff_text` excluded; test_loop_ledger_lists.py).
    They are reads, added HERE deliberately because this set is exhaustive on
    purpose: a new method must appear in this diff, where its verdict-writing
    potential gets reviewed, and the INSERT scan below covers it forever."""
    public = {n for n in dir(ledger.ProposerLedger) if not n.startswith("_")}
    assert public == {"check", "record_proposal", "close", "proposal", "history",
                      "judge_run", "verdict", "replay_record", "verify_chain",
                      "list_proposals", "list_judge_runs", "list_verdicts"}, public
    for name in public:
        src = inspect.getsource(getattr(ledger.ProposerLedger, name))
        assert not re.search(r"INSERT\s+INTO\s+loop_verdicts", src, re.I), name


def code_of(path: Path) -> str:
    """Source with docstrings and `#` comments removed.

    A gate that greps raw text cannot tell an INSERT from a sentence ABOUT an
    INSERT, so it goes red when someone documents the rule — and the cheapest
    way to fix that gate is to stop documenting the rule. Parse instead.
    """
    src = path.read_text(encoding="utf-8", errors="replace")
    drop: set[int] = set()
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        body = getattr(node, "body", None)
        if not body or not isinstance(body[0], ast.Expr):
            continue
        val = body[0].value
        if isinstance(val, ast.Constant) and isinstance(val.value, str):
            drop.update(range(val.lineno, (val.end_lineno or val.lineno) + 1))
    keep = [line for i, line in enumerate(src.splitlines(), 1)
            if i not in drop and not line.strip().startswith("#")]
    return "\n".join(keep)


def test_only_one_place_in_the_estate_inserts_a_verdict():
    """§8.1's `test_loop_verdict_writer_is_singular` — a second INSERT anywhere
    is a second writer, and a second writer is a second identity."""
    hits = []
    for py in (REPO / "files/anatomy").rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        if re.search(r"INSERT\s+INTO\s+loop_verdicts", code_of(py), re.I):
            hits.append(str(py.relative_to(REPO)))
    assert hits == ["files/anatomy/bone/ledger.py"], hits
    assert len(re.findall(r"INSERT\s+INTO\s+loop_verdicts",
                          code_of(BONE / "ledger.py"), re.I)) == 1


def test_the_single_verdict_insert_lives_inside_seal_verdict():
    src = inspect.getsource(ledger.EvaluatorLedger.seal_verdict)
    assert re.search(r"INSERT\s+INTO\s+loop_verdicts", src, re.I)


# ══════════════════════════════════════════════════════════════════════════
# LAYER 2 — the connection refuses it  (THE ADVERSARIAL CASE)
# ══════════════════════════════════════════════════════════════════════════

VERDICT_FORGERY = (
    "INSERT INTO loop_verdicts "
    "(uuid, gate_set, result, actor, tree_sha, evidence) "
    "VALUES ('forged','fast','pass',?,'aaaa','{}')"
)


def test_ADVERSARIAL_proposer_write_helper_cannot_insert_a_verdict(proposer):
    """Attempt a verdict THROUGH the proposer path. It must be refused.

    `_w` is the proposer's own write helper — the same call `record_proposal`
    uses successfully. Pointed at `loop_verdicts` it is denied by the sqlite3
    authorizer bound to the proposer's connection, so the refusal does not
    depend on anyone remembering not to call it.
    """
    with pytest.raises(sqlite3.DatabaseError) as e:
        proposer._w(VERDICT_FORGERY, (ledger.ENGINE_ACTOR,))
    assert "not authorized" in str(e.value)


def test_ADVERSARIAL_proposer_raw_connection_cannot_insert_a_verdict(proposer, db):
    """Encapsulation already broken — the attacker holds the proposer's OWN
    connection object — and the write is STILL refused. This is the difference
    between a convention and a mechanism."""
    conn = proposer._ReaderLedger__conn          # name mangling deliberately defeated
    with pytest.raises(sqlite3.DatabaseError) as e:
        conn.execute(VERDICT_FORGERY, (ledger.ENGINE_ACTOR,))
    assert "not authorized" in str(e.value)
    assert raw(db).execute("SELECT COUNT(*) FROM loop_verdicts").fetchone()[0] == 0


def test_ADVERSARIAL_proposer_cannot_fabricate_judge_run_evidence(proposer):
    """A verdict is derived from `loop_judge_runs`. Denying only the verdict
    table while leaving its INPUT writable would move the forgery one table
    left, not prevent it."""
    with pytest.raises(sqlite3.DatabaseError) as e:
        proposer._w(
            "INSERT INTO loop_judge_runs (uuid, gate_set, judge_name, argv, status, "
            "started_at, exit_code, work_count, outcome) "
            "VALUES ('f','fast','ansible-lint','[]','exited','now',0,99999,'pass')")
    assert "not authorized" in str(e.value)


def test_ADVERSARIAL_proposer_cannot_drop_the_worm_triggers(proposer):
    """M6 — `test_audit_chain.py:188` drops a WORM trigger to simulate an
    offline attacker. Through this module's connections that route is closed;
    an attacker must go AROUND the ledger, where the chain records the fact."""
    for sql in ("DROP TRIGGER loop_verdicts_worm_update",
                "DROP TABLE loop_verdicts",
                "ALTER TABLE loop_verdicts RENAME TO x"):
        with pytest.raises(sqlite3.DatabaseError) as e:
            proposer._w(sql)
        assert "not authorized" in str(e.value), sql


def test_ADVERSARIAL_proposer_cannot_attach_a_second_handle_to_the_same_file(proposer, db):
    """ATTACH would re-open the same file under a schema name the authorizer's
    table checks never see."""
    with pytest.raises(sqlite3.DatabaseError) as e:
        proposer._w(f"ATTACH DATABASE '{db}' AS side")
    assert "not authorized" in str(e.value)


def test_role_write_matrix_is_exhaustive(db):
    """Each role writes exactly its own tables. Any cell flipping to ALLOWED is
    a capability nobody asked for."""
    tables = {
        "loop_proposals": "INSERT INTO loop_proposals (uuid,fingerprint,weakness_id,"
                          "intent_class,gate_set,target_paths,tree_sha,proposer_id) "
                          "VALUES ('u','f','w','config-fix','fast','[]','t','p')",
        "loop_judge_runs": "INSERT INTO loop_judge_runs (uuid,gate_set,judge_name,argv,"
                           "status,started_at) VALUES ('u','fast','j','[]','running','n')",
        "loop_verdicts": VERDICT_FORGERY.replace("?", "'engine:judge-runner'"),
        "loop_forgets": "INSERT INTO loop_forgets (fingerprint,through_proposal_id,actor) "
                        "VALUES ('f',0,'operator')",
    }
    expected = {
        "proposer": {"loop_proposals"},
        "evaluator": {"loop_judge_runs", "loop_verdicts"},
        "operator": {"loop_forgets"},
        "reader": set(),
    }
    for role, allowed in expected.items():
        led = ledger.open_ledger(role)
        try:
            for table, sql in tables.items():
                if table in allowed:
                    led._w(sql)                      # must succeed
                else:
                    with pytest.raises(sqlite3.DatabaseError) as e:
                        led._w(sql)
                    assert "not authorized" in str(e.value), (role, table)
        finally:
            led.close()


# ══════════════════════════════════════════════════════════════════════════
# LAYER 3 — the schema refuses it
# ══════════════════════════════════════════════════════════════════════════

def test_ADVERSARIAL_schema_refuses_a_non_engine_actor(db):
    """§3.3(2) — even on an UNRESTRICTED connection, a verdict naming another
    writer is rejected by `CHECK (actor = 'engine:judge-runner')`."""
    ledger.ensure_schema(raw(db))
    conn = raw(db)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(VERDICT_FORGERY, ("agent:remediator",))
    conn.execute(VERDICT_FORGERY, (ledger.ENGINE_ACTOR,))   # control: the CHECK is real
    assert conn.execute("SELECT COUNT(*) FROM loop_verdicts").fetchone()[0] == 1


def test_result_column_admits_exactly_the_three_declared_values(db):
    assert set(ledger.RESULTS) == {r.value for r in judges.Result}


def test_result_column_rejects_a_fourth_value(db):
    ledger.ensure_schema(raw(db))
    conn = raw(db)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO loop_verdicts (uuid,gate_set,result,actor,tree_sha,evidence) "
            "VALUES ('x','fast','mostly-green',?,'t','{}')", (ledger.ENGINE_ACTOR,))


# ══════════════════════════════════════════════════════════════════════════
# LAYER 4 — WORM refuses edits
# ══════════════════════════════════════════════════════════════════════════

def test_ADVERSARIAL_worm_refuses_rewriting_a_verdict(db, evaluator):
    v = judge_set(evaluator, [(LINT, 2, LINT_OK)])
    assert v["result"] == "fail"
    conn = raw(db)
    with pytest.raises(sqlite3.IntegrityError) as e:
        conn.execute("UPDATE loop_verdicts SET result='pass' WHERE uuid=?", (v["uuid"],))
    assert "append-only" in str(e.value)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM loop_verdicts WHERE uuid=?", (v["uuid"],))
    assert raw(db).execute("SELECT result FROM loop_verdicts").fetchone()[0] == "fail"


def test_ADVERSARIAL_worm_refuses_rewriting_a_finished_run(db, evaluator):
    """Constraint B's other half: an exit code that has been read cannot be
    re-written afterwards, so a losing run cannot be edited into a winning one
    and re-sealed."""
    u = evaluator.begin_judge_run(gate_set="fast", judge_name="ansible-lint", argv=["x"])
    evaluator.finish_judge_run(u, run=derive(LINT, 2, LINT_OK))
    with pytest.raises(sqlite3.IntegrityError) as e:
        raw(db).execute("UPDATE loop_judge_runs SET exit_code=0, outcome='pass' WHERE uuid=?", (u,))
    assert "immutable" in str(e.value)


# ══════════════════════════════════════════════════════════════════════════
# LAYER 5 — honest ceiling: detected, NOT prevented
# ══════════════════════════════════════════════════════════════════════════

def test_ADVERSARIAL_offline_forgery_is_detected_not_prevented(db, evaluator):
    """The claim §3.3(3) actually makes, proved in both directions.

    An attacker with the DB file drops the trigger (M6) and inserts a green
    verdict naming the engine. The INSERT SUCCEEDS — pretending otherwise would
    be the decorative gate constraint C forbids — and `verify_chain()` reports
    BROKEN, which is the guarantee that was on offer.
    """
    judge_set(evaluator, [(LINT, 0, LINT_OK)])
    assert evaluator.verify_chain()["ok"] is True

    conn = raw(db)
    conn.execute("DROP TRIGGER loop_verdicts_worm_update")     # the M6 bypass
    conn.execute(
        "INSERT INTO loop_verdicts (uuid,gate_set,result,actor,tree_sha,evidence,row_hash) "
        "VALUES ('forged','fast','pass',?,'aaaa','{}','deadbeef')", (ledger.ENGINE_ACTOR,))
    conn.commit()

    report = evaluator.verify_chain()
    assert report["ok"] is False and report["broken_uuid"] == "forged"


# ══════════════════════════════════════════════════════════════════════════
# CONSTRAINT B — derived from the effect, never asserted by the actor
# ══════════════════════════════════════════════════════════════════════════

def test_run_row_exists_before_any_outcome_does(db, evaluator):
    u = evaluator.begin_judge_run(gate_set="fast", judge_name="ansible-lint", argv=["x"])
    row = evaluator.judge_run(u)
    assert row["status"] == "running"
    assert row["outcome"] is None and row["exit_code"] is None and row["finished_at"] is None


def test_killed_run_sweeps_to_crashed_and_can_never_pass(db, evaluator):
    """The normal failure mode of an unattended loop: the process dies, the
    exit reader never returns. The row must not stay claimable."""
    u = evaluator.begin_judge_run(gate_set="solo", judge_name="ansible-lint", argv=["x"])
    assert evaluator.sweep_crashed() == 1
    assert evaluator.judge_run(u)["outcome"] == "indeterminate"
    v = evaluator.seal_verdict(gate_set="solo")
    assert v["result"] == "indeterminate"


def test_a_swept_run_cannot_be_finished_afterwards(db, evaluator):
    """The subtle half, and this test found it: the `status='running'` guard
    made the resurrecting UPDATE a NO-OP — while `finish_judge_run` still
    RETURNED `outcome='pass'` to its caller. A step reporting a success it did
    not record is precisely the v0.10-beta defect, reproduced inside the engine
    built to detect it. It must raise, not shrug."""
    u = evaluator.begin_judge_run(gate_set="fast", judge_name="ansible-lint", argv=["x"])
    evaluator.sweep_crashed()
    with pytest.raises(ledger.LedgerError) as e:
        evaluator.finish_judge_run(u, run=derive(LINT, 0, LINT_OK))
    assert "not persisted" in str(e.value)
    assert evaluator.judge_run(u)["outcome"] == "indeterminate"


# ── §2.4: absence is never success (M2 / M3 / corpus-diff) ────────────────
#
# The DERIVATION lives in judges.py and is pinned by its own suite. What is
# pinned HERE is the ledger's independent half: that these shapes reach the
# database as INDETERMINATE, and that a PASS which cannot show its work is not
# storable at all — even if a future runner forgets the rule.

def test_zero_work_with_exit_zero_reaches_the_ledger_as_indeterminate(db, evaluator):
    """M2 — `nos-smoke --include zzz-nonexistent-service` prints "smoke catalog
    yielded zero entries" and exits 0. The loop's own judges carry the exact
    defect the loop exists to detect."""
    v = judge_set(evaluator, [(SMOKE, 0, "smoke catalog yielded zero entries")])
    assert v["result"] == "indeterminate"
    assert raw(db).execute("SELECT outcome FROM loop_judge_runs").fetchone()[0] == "indeterminate"


def test_pytest_all_skipped_reaches_the_ledger_as_indeterminate(db, evaluator):
    """M3 — `2 skipped`, exit 0, on a host with no WING_API_TOKEN."""
    assert judge_set(evaluator, [(PYTEST_J, 0, "2 skipped in 0.22s")])["result"] == "indeterminate"
    assert judge_set(evaluator, [(PYTEST_J, 0, "41 passed, 2 skipped in 9.1s")])["result"] == "pass"


def test_scope_loss_below_the_ratchet_is_indeterminate(db, evaluator):
    """§2.1 — ansible-lint processing 12 files instead of 1400 is silent scope
    loss that would otherwise read green."""
    assert judge_set(evaluator, [(LINT, 0, "12 files processed")])["result"] == "indeterminate"
    assert judge_set(evaluator, [(LINT, 0, LINT_OK)])["result"] == "pass"


def test_ADVERSARIAL_a_pass_that_did_no_work_cannot_BE_STORED(db):
    """The ledger's own contribution to §2.4, and the reason it is not merely a
    duplicate of the adapter: the invariant is a CHECK, so it holds for rows
    written by a runner that never applied the ratchet — or by an attacker with
    a SQL client and no authorizer."""
    ledger.ensure_schema(raw(db))
    conn = raw(db)
    insert = ("INSERT INTO loop_judge_runs (uuid,gate_set,judge_name,argv,status,"
              "started_at,exit_code,work_count,min_work,outcome) VALUES "
              "('u','fast','ansible-lint','[]','exited','now',0,?,1400,'pass')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(insert, (None,))          # cannot show its work
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(insert, (12,))            # work below the ratchet
    conn.execute(insert, (1500,))              # control: a real pass stores fine


def test_ADVERSARIAL_a_crashed_run_cannot_be_stored_as_a_pass(db):
    ledger.ensure_schema(raw(db))
    with pytest.raises(sqlite3.IntegrityError):
        raw(db).execute(
            "INSERT INTO loop_judge_runs (uuid,gate_set,judge_name,argv,status,"
            "started_at,exit_code,work_count,min_work,outcome) VALUES "
            "('u','fast','ansible-lint','[]','crashed','now',0,9999,1,'pass')")


def test_ansible_lint_work_line_on_stderr_still_counts(db, evaluator):
    """MEASURED by judges.py: ansible-lint writes "… 1400 files processed" to
    STDERR. A ledger that had kept its own stdout-only parser would have
    recorded every green ansible-lint run as INDETERMINATE — which is exactly
    the drift a second implementation buys."""
    run = derive(LINT, 0, stdout="", stderr="Passed: 0 failure(s) in 1500 files processed")
    u = evaluator.begin_judge_run(gate_set="fast", judge_name=LINT.name, argv=run.argv)
    evaluator.finish_judge_run(u, run=run)
    assert evaluator.judge_run(u)["outcome"] == "pass"


def test_corpus_diff_disagrees_while_exiting_zero(db, evaluator):
    """§2.2 — exit 0 while the report says DISAGREE."""
    agree = '{"agrees": true, "nodes": 790}'
    assert judge_set(evaluator, [(CORPUS, 0, '{"agrees": false, "nodes": 790}')])["result"] == "fail"
    assert judge_set(evaluator, [(CORPUS, 0, agree)])["result"] == "pass"
    # organ down → prints nothing, still exits 0 → never a pass
    assert judge_set(evaluator, [(CORPUS, 0, "night VOID")])["result"] == "indeterminate"


def test_ansible_lint_fails_with_2_and_1_is_indeterminate(db, evaluator):
    """§2.2 — a naive `!= 0` is right by accident, a naive `== 1` is wrong."""
    assert judge_set(evaluator, [(LINT, 2, LINT_OK)])["result"] == "fail"
    assert judge_set(evaluator, [(LINT, 1, LINT_OK)])["result"] == "indeterminate"


def test_smoke_exit_code_is_a_failure_count_not_a_boolean(db, evaluator):
    assert judge_set(evaluator, [(SMOKE, 3, "48 entries")])["result"] == "fail"
    assert judge_set(evaluator, [(SMOKE, 0, "48 entries")])["result"] == "pass"


def test_a_set_passes_only_if_every_expected_judge_passed(db, evaluator):
    """§2.3 DECISION 2a — no majority, no weighting, no "mostly green"."""
    v = judge_set(evaluator, [(LINT, 0, LINT_OK), (CODEGEN, 0, CODEGEN_OK)])
    assert v["result"] == "pass"
    v = judge_set(evaluator, [(LINT, 0, LINT_OK), (CODEGEN, 1, CODEGEN_STALE)])
    assert v["result"] == "fail"


def test_a_judge_that_never_reported_makes_the_set_indeterminate(db, evaluator):
    """Absence at the AGGREGATION layer, not just the adapter layer: one green
    judge out of an expected two is not a green set."""
    u = evaluator.begin_judge_run(gate_set="fast", judge_name="ansible-lint", argv=["x"])
    evaluator.finish_judge_run(u, run=derive(LINT, 0, LINT_OK))
    v = evaluator.seal_verdict(gate_set="fast")
    assert v["result"] == "indeterminate"
    assert json.loads(v["evidence"])["missing_judges"] == ["genome-codegen"]


def test_an_empty_set_is_indeterminate_never_pass(db, evaluator):
    """hidden_fees/08 in one line: `0/0 ready` must not be green."""
    v = evaluator.seal_verdict(gate_set="probe")
    assert v["result"] == "indeterminate"


# ══════════════════════════════════════════════════════════════════════════
# §2.4, one layer up — a SELECTED absence, which the empty-set rule misses
# ══════════════════════════════════════════════════════════════════════════

def test_ADVERSARIAL_a_fail_on_record_cannot_be_left_out_of_the_verdict(db, proposer, evaluator):
    """MEASURED against the previous code: one PASS run and one FAIL run
    persisted against the SAME proposal, sealed with `run_uuids=[the pass]` and
    `expected_judges=[]`, produced `result='pass'` — and `verify_chain()` said
    ok, because nothing was tampered with. The verdict came through the front
    door.

    `aggregate` refuses an EMPTY set (absence is never success). This is the
    same rule one layer up: a SELECTED absence. The FAIL is not missing from the
    database, it is missing from the caller's list — so the caller no longer has
    a list.
    """
    p = propose(proposer, diff_text=mkdiff("b"))
    for judge, code, out in ((LINT, 0, LINT_OK), (CODEGEN, 1, CODEGEN_STALE)):
        run = derive(judge, code, out)
        u = evaluator.begin_judge_run(gate_set="fast", judge_name=judge.name,
                                      argv=run.argv, proposal_uuid=p["uuid"])
        evaluator.finish_judge_run(u, run=run)

    v = evaluator.seal_verdict(gate_set="fast", proposal_uuid=p["uuid"])
    assert v["result"] == "fail", (
        "a PASS was assembled while a FAIL for the same proposal was on record")
    assert set(json.loads(v["evidence"])["outcomes"]) == {"ansible-lint", "genome-codegen"}


def test_ADVERSARIAL_a_green_run_cannot_be_reattached_to_another_proposal(db, proposer, evaluator):
    """The second measured shape: a `fast` run of proposal A, re-offered as the
    evidence for proposal B on gate set `full` at tree 'zzz', sealed 'pass'.

    Rows were fetched by uuid with no filter on proposal_id or gate_set, so a
    green run was portable across every axis a verdict is supposed to be about.
    Here B is sealed while A's green run exists, and B must find nothing of its
    own — an empty set, which is INDETERMINATE.
    """
    a = propose(proposer, diff_text=mkdiff("b"))
    # DELIBERATELY LEFT UNSEALED. Sealing A first would put its run in the
    # consumed set, and the consumed-once rule would then hide whether the
    # proposal filter works at all — the mutation harness caught exactly that:
    # this gate stayed GREEN with the proposal filter removed.
    run = derive(LINT, 0, LINT_OK)
    ua = evaluator.begin_judge_run(gate_set="solo", judge_name=LINT.name,
                                   argv=run.argv, proposal_uuid=a["uuid"])
    evaluator.finish_judge_run(ua, run=run)

    b = propose(proposer, weakness_id="REM-137",
                target_paths=["roles/pazny.n8n/defaults/main.yml"],
                diff_text=mkdiff("y", path="roles/pazny.n8n/defaults/main.yml"))
    v = evaluator.seal_verdict(gate_set="solo", proposal_uuid=b["uuid"])
    assert v["result"] == "indeterminate", "another proposal's green run sealed this one"
    assert json.loads(v["evidence"])["judge_runs"] == []
    # …and A's run is still unspent, so it was filtered out rather than consumed.
    assert evaluator.seal_verdict(
        gate_set="solo", proposal_uuid=a["uuid"])["result"] == "pass"


def test_ADVERSARIAL_judges_that_saw_two_trees_cannot_pass(db, proposer, evaluator):
    """§2.5 at the ledger layer.

    `judges.py` now runs a whole set in ONE sandbox, so this shape should be
    unreachable from the runner. It is pinned here anyway because the ledger is
    the last reader before the hash chain closes over the row: a verdict that
    names one `tree_sha` while its evidence names two is a verdict about nothing.
    """
    p = propose(proposer, diff_text=mkdiff("b"))
    for judge, sha in ((LINT, "a" * 40), (CODEGEN, "b" * 40)):
        out = LINT_OK if judge is LINT else CODEGEN_OK
        run = derive(judge, 0, out, tree_sha=sha)
        u = evaluator.begin_judge_run(gate_set="fast", judge_name=judge.name,
                                      argv=run.argv, proposal_uuid=p["uuid"])
        evaluator.finish_judge_run(u, run=run)

    v = evaluator.seal_verdict(gate_set="fast", proposal_uuid=p["uuid"])
    assert v["result"] == "indeterminate"
    assert v["tree_sha"] == "", "a verdict named one tree while its judges saw two"
    assert json.loads(v["evidence"])["trees"] == ["a" * 40, "b" * 40]


def test_a_verdict_names_the_tree_its_judges_read_out_of_the_sandbox(db, proposer, evaluator):
    """The control for the two tests above: agreement seals cleanly, and the
    sha on the row is the one the RUNS carry — never a caller's label."""
    p = propose(proposer, diff_text=mkdiff("b"))
    v = judge_set(evaluator, [(LINT, 0, LINT_OK), (CODEGEN, 0, CODEGEN_OK)],
                  gate_set="fast", proposal_uuid=p["uuid"], tree_sha="d" * 40)
    assert v["result"] == "pass"
    assert v["tree_sha"] == "d" * 40
    assert evaluator.replay_record(v["uuid"])["runs"][0]["tree_sha"] == "d" * 40


def test_ADVERSARIAL_the_same_run_cannot_be_sealed_twice(db, proposer, evaluator):
    """Evidence is consumed once, or "every run on record" would re-seal an
    earlier attempt's greens into a later attempt's verdict."""
    p = propose(proposer, diff_text=mkdiff("b"))
    first = judge_set(evaluator, [(LINT, 0, LINT_OK)], gate_set="solo",
                      proposal_uuid=p["uuid"])
    assert first["result"] == "pass"
    second = evaluator.seal_verdict(gate_set="solo", proposal_uuid=p["uuid"])
    assert second["result"] == "indeterminate"
    assert json.loads(second["evidence"])["judge_runs"] == []


# ══════════════════════════════════════════════════════════════════════════
# §4 — FINGERPRINTING
# ══════════════════════════════════════════════════════════════════════════

def test_fingerprint_ignores_the_diff_entirely():
    """The load-bearing exclusion. If the diff were in this hash a proposer
    would defeat dedup by perturbing whitespace — the retry loop would optimise
    against the deduplicator, which is §2's failure mode one level down."""
    args = ("REM-137", ["roles/pazny.gitea/defaults/main.yml"], "version-pin-bump", "repo")
    assert ledger.fingerprint(*args) == ledger.fingerprint(*args)
    assert "diff" not in inspect.signature(ledger.fingerprint).parameters


def test_fingerprint_is_stable_under_path_order_and_duplication():
    a = ledger.fingerprint("w", ["b.yml", "a.yml"], "config-fix", "fast")
    b = ledger.fingerprint("w", ["./a.yml", "b.yml", "a.yml"], "config-fix", "fast")
    assert a == b


def test_fingerprint_changes_with_gate_set_so_the_block_lifts():
    """§4 — "the gate set changes, which changes the fingerprint by
    construction"."""
    a = ledger.fingerprint("w", ["a.yml"], "config-fix", "fast")
    b = ledger.fingerprint("w", ["a.yml"], "config-fix", "repo")
    assert a != b


def test_content_fp_ignores_hunk_offsets_but_not_content():
    d1 = "--- a/x.yml\t2026-08-02\n+++ b/x.yml\t2026-08-02\n@@ -1,3 +1,3 @@\n-a\n+b\n"
    d2 = "--- a/x.yml\t2026-09-09\n+++ b/x.yml\t2026-09-09\n@@ -40,3 +40,3 @@\n-a\n+b\n"
    d3 = "--- a/x.yml\n+++ b/x.yml\n@@ -1,3 +1,3 @@\n-a\n+c\n"
    assert ledger.content_fingerprint(d1) == ledger.content_fingerprint(d2)
    assert ledger.content_fingerprint(d1) != ledger.content_fingerprint(d3)


def test_unknown_intent_class_is_refused():
    with pytest.raises(ledger.ProposalRefused) as e:
        ledger.fingerprint("w", ["a.yml"], "rewrite-everything", "fast")
    assert e.value.reason == "unknown-intent"


def test_paths_that_escape_the_repo_are_refused():
    for bad in ["/etc/passwd", "../../.ssh/id_rsa", "~/.nos/secrets.yml"]:
        with pytest.raises(ledger.ProposalRefused) as e:
            ledger.fingerprint("w", [bad], "config-fix", "fast")
        assert e.value.reason == "bad-path", bad


# ══════════════════════════════════════════════════════════════════════════
# §4 — "ALREADY FAILED, REFUSE WITHOUT RUNNING"
# ══════════════════════════════════════════════════════════════════════════

def _fail_one_attempt(prop, ev, diff: str):
    p = propose(prop, diff_text=diff)
    judge_set(ev, [(LINT, 2, LINT_OK)], proposal_uuid=p["uuid"])
    return p


def test_exhausted_fingerprint_is_refused_without_running_a_judge(db, proposer, evaluator):
    """THE path this ledger exists for: two attempts at the same weakness, in
    the same place, with the same intent, both judged FAIL. The third is
    refused BEFORE anything runs — no sandbox, no 190 s of pytest, no run row.
    """
    _fail_one_attempt(proposer, evaluator, mkdiff("b"))
    _fail_one_attempt(proposer, evaluator, mkdiff("c"))

    runs_before = raw(db).execute("SELECT COUNT(*) FROM loop_judge_runs").fetchone()[0]
    props_before = raw(db).execute("SELECT COUNT(*) FROM loop_proposals").fetchone()[0]

    with pytest.raises(ledger.ProposalRefused) as e:
        propose(proposer, diff_text=mkdiff("d"))
    assert e.value.reason == "already-failed"
    assert e.value.status == 409

    after = raw(db)
    assert after.execute("SELECT COUNT(*) FROM loop_judge_runs").fetchone()[0] == runs_before
    assert after.execute("SELECT COUNT(*) FROM loop_proposals").fetchone()[0] == props_before


def test_a_refused_proposal_has_no_uuid_so_no_judge_can_be_run_for_it(db, proposer, evaluator):
    """The refusal is not advisory. There is no proposal row, and
    `begin_judge_run` will not attach a run to a proposal that does not
    exist — so a caller that ignores the 409 still cannot spend the budget."""
    with pytest.raises(ledger.LedgerError):
        evaluator.begin_judge_run(gate_set="fast", judge_name="ansible-lint",
                                  argv=["x"], proposal_uuid="never-issued-uuid")


def test_byte_identical_patch_is_refused_even_on_attempt_one(db, proposer, evaluator):
    """A no-op retry carries no new information, whatever the attempt count."""
    _fail_one_attempt(proposer, evaluator, mkdiff("b"))
    with pytest.raises(ledger.ProposalRefused) as e:
        propose(proposer, diff_text=mkdiff("b", at=99))   # same content, new offsets
    assert e.value.reason == "content-fp-repeat"


def test_an_unjudged_attempt_blocks_the_next_one(db, proposer):
    """§5.4 — one proposal per cycle. An attempt with no verdict yet is not a
    licence to open a second."""
    propose(proposer, diff_text=mkdiff("b"))
    with pytest.raises(ledger.ProposalRefused) as e:
        propose(proposer, diff_text=mkdiff("c"))
    assert e.value.reason == "attempt-pending"


def _pass_one_attempt(prop, ev, diff: str):
    p = propose(prop, diff_text=diff)
    judge_set(ev, [(LINT, 0, LINT_OK)], proposal_uuid=p["uuid"])
    return p


def test_a_solved_weakness_is_remembered_as_awaiting_an_act(db, proposer, evaluator, monkeypatch):
    """Fable review §3.2, measured live: `rem:REM-204` held two sealed `pass`
    verdicts and the tree still read the old pin, and the ledger's only word
    for it was `fingerprint-exhausted` — the same word it uses for a proposal
    that went nowhere. A weakness the loop SOLVED must refuse the next attempt
    with a reason that names what it waits for (merge → converge → rescan,
    all outside the loop), and it must do so on attempt ONE of two: the pass
    is the operative fact, not the ceiling.

    The referee is pinned to 'applies': this test is about the refusal shape,
    and the fixture diff is stale against the real checkout by construction.
    """
    monkeypatch.setattr(ledger.judges, "patch_state_at_head", lambda d: "applies")
    _pass_one_attempt(proposer, evaluator, mkdiff("b"))
    with pytest.raises(ledger.ProposalRefused) as e:
        propose(proposer, diff_text=mkdiff("c"))
    assert e.value.reason == "passed-awaiting-act", (
        f"a solved weakness was refused as {e.value.reason!r}; the state that "
        f"says WHY it waits is the whole point of the reason enum"
    )
    assert e.value.status == 409
    assert e.value.prior, "the refusal must carry the passed attempt as evidence"


def test_awaiting_act_outranks_the_attempt_ceiling(db, proposer, evaluator, monkeypatch):
    """Fail then pass, ceiling reached: the answer is still the pass. A reader
    told `fingerprint-exhausted` re-judges (measured: that is exactly what
    happened to 6f139e22, twice, and changed nothing); a reader told
    `passed-awaiting-act` goes to the merge queue instead."""
    monkeypatch.setattr(ledger.judges, "patch_state_at_head", lambda d: "applies")
    _fail_one_attempt(proposer, evaluator, mkdiff("b"))
    _pass_one_attempt(proposer, evaluator, mkdiff("c"))
    with pytest.raises(ledger.ProposalRefused) as e:
        propose(proposer, diff_text=mkdiff("d"))
    assert e.value.reason == "passed-awaiting-act"


def _repo_holding(tmp_path, first_line: str):
    """A one-commit repo whose DEFAULT_TARGET starts with `first_line`, handed
    to `judges.patch_state_at_head` explicitly — never via env, which would
    also repoint the gate-set registry these fixtures resolve."""
    import subprocess as sp
    root = tmp_path / "repo"
    (root / "roles/pazny.gitea/defaults").mkdir(parents=True)
    (root / DEFAULT_TARGET).write_text(f"{first_line}\n")
    for argv in (["init", "-q"], ["add", "-A"],
                 ["-c", "user.email=t@t", "-c", "user.name=t",
                  "commit", "-qm", "base"]):
        sp.run(["git", "-C", str(root), *argv], check=True, capture_output=True)
    return root


def test_patch_state_at_head_reads_the_three_states(tmp_path):
    """The referee itself, against real repos: old content = applies, new
    content = landed, neither = stale."""
    import judges
    diff = mkdiff("c")
    assert judges.patch_state_at_head(diff, _repo_holding(tmp_path / "1", "a")) == "applies"
    assert judges.patch_state_at_head(diff, _repo_holding(tmp_path / "2", "c")) == "landed"
    assert judges.patch_state_at_head(diff, _repo_holding(tmp_path / "3", "zzz")) == "stale"


def test_a_pass_the_tree_moved_under_is_void_and_the_weakness_reopens(
        db, proposer, evaluator, monkeypatch):
    """Measured 2026-09-03: rem:REM-204's passed patch fits neither forward
    nor reversed at HEAD (`--awaiting` state `conflict`), yet the ledger still
    refused every new attempt with `passed-awaiting-act` and the picker read
    the pass as settled — double-locked, `forget` the only key, one forget
    row ever recorded. The tree is the referee: a pass git can no longer read
    into OR out of the tree stops blocking, and stops counting."""
    monkeypatch.setattr(ledger.judges, "patch_state_at_head", lambda d: "stale")
    _pass_one_attempt(proposer, evaluator, mkdiff("c"))
    got = propose(proposer, diff_text=mkdiff("d"))
    assert got["uuid"], (
        "a passed-then-conflicted weakness still refuses new proposals — the "
        "double-lock stands and only `forget` can open it")


def test_a_landed_pass_still_refuses_the_next_attempt(
        db, proposer, evaluator, monkeypatch):
    """Reverse-applies = the change IS in the tree; what is missing is
    converge → rescan, outside the loop. Same refusal as applies."""
    monkeypatch.setattr(ledger.judges, "patch_state_at_head", lambda d: "landed")
    _pass_one_attempt(proposer, evaluator, mkdiff("c"))
    with pytest.raises(ledger.ProposalRefused) as e:
        propose(proposer, diff_text=mkdiff("d"))
    assert e.value.reason == "passed-awaiting-act"


def test_an_unanswered_referee_refuses_conservatively(
        db, proposer, evaluator, monkeypatch):
    """'unknown' must behave exactly like 'applies' — a pass is never voided
    on a question that went unanswered."""
    monkeypatch.setattr(ledger.judges, "patch_state_at_head", lambda d: "unknown")
    _pass_one_attempt(proposer, evaluator, mkdiff("c"))
    with pytest.raises(ledger.ProposalRefused) as e:
        propose(proposer, diff_text=mkdiff("d"))
    assert e.value.reason == "passed-awaiting-act"


def test_the_latest_verdict_is_THE_verdict(db, proposer, evaluator):
    """`tools/loop-status.py` invented `ORDER BY id DESC LIMIT 1` because
    nothing said which verdict counts. Now the ledger says: a proposal whose
    pass was later re-judged FAIL is not awaiting anything."""
    p = _pass_one_attempt(proposer, evaluator, mkdiff("b"))
    judge_set(evaluator, [(LINT, 2, LINT_OK)], proposal_uuid=p["uuid"])
    _fail_one_attempt(proposer, evaluator, mkdiff("c"))
    with pytest.raises(ledger.ProposalRefused) as e:
        propose(proposer, diff_text=mkdiff("d"))
    assert e.value.reason == "already-failed", (
        f"got {e.value.reason!r}: a superseded pass still counted as THE "
        f"verdict — the latest-by-rowid rule is not being applied"
    )


def test_awaiting_act_lifts_when_the_weakness_evidence_changes(db, proposer, evaluator):
    """The same two lifts as the ceiling: the scanner re-scans after a converge,
    the evidence sha moves, and the fingerprint is a different world — which is
    exactly the honest exit (§11: merge → converge → rescan → retire)."""
    _pass_one_attempt(proposer, evaluator, mkdiff("b"))
    index = dict(WEAKNESS_INDEX, **{"hidden-fee:08": "sha-08-CONVERGED"})
    lifted = ledger.open_ledger("proposer", registry=TEST_REGISTRY, weakness_index=index)
    try:
        ok = propose(lifted, diff_text=mkdiff("z"))
    finally:
        lifted.close()
    assert ok["attempt_n"] == 1


def test_the_block_lifts_when_the_weakness_evidence_changes(db, proposer, evaluator):
    """§4 — "or the ledger becomes a permanent scar". The remediation item's
    fix_version moved; this is a different world and deserves a new attempt.

    THE LIFT IS DRIVEN FROM THE SOURCE, not from the proposal. The earlier
    version of this test passed a literal `weakness_evidence_sha="sha-NEW"` and
    so encoded the lift without encoding WHO may assert it — which is precisely
    the defect: four attempts at the same substantive change were all accepted
    by supplying a fresh nonce. Here the SOURCE's evidence changes (the reader's
    index moves) and the proposal says nothing about it.
    """
    _fail_one_attempt(proposer, evaluator, mkdiff("b"))
    _fail_one_attempt(proposer, evaluator, mkdiff("c"))
    with pytest.raises(ledger.ProposalRefused):
        propose(proposer, diff_text=mkdiff("d"))

    index = dict(WEAKNESS_INDEX, **{"hidden-fee:08": "sha-08-MOVED"})
    lifted = ledger.open_ledger("proposer", registry=TEST_REGISTRY, weakness_index=index)
    try:
        ok = propose(lifted, diff_text=mkdiff("d"))
    finally:
        lifted.close()
    assert ok["attempt_n"] == 1


def test_ADVERSARIAL_a_fresh_nonce_does_not_buy_a_fresh_attempt(db, proposer, evaluator):
    """§4's ceiling is the only defence against grinding a flaky judge green.

    MEASURED against the previous code: four proposals identical in
    weakness_id / paths / intent / gate_set, each sealed FAIL, each supplying a
    fresh `weakness_evidence_sha` — 4/4 ACCEPTED. Varying `weakness_id` instead:
    also 4/4. `state/judge-sets.yml` declares `nos-smoke` and
    `cortex-corpus-diff` `deterministic: false`, so an unattended proposer that
    re-offers the same change under a new nonce until one comes back green has
    captured the verdict without touching a gate.

    Neither field is a parameter any more, so the grind has nothing to vary —
    and `record_proposal`'s signature is the assertion.
    """
    params = set(inspect.signature(ledger.ProposerLedger.record_proposal).parameters)
    assert "weakness_evidence_sha" not in params, (
        "the lift key is caller-supplied again; a lift the blocked party asserts "
        "is not a ceiling")
    assert "weakness_evidence_sha" not in set(
        inspect.signature(ledger.ProposerLedger.check).parameters)

    _fail_one_attempt(proposer, evaluator, mkdiff("b"))
    _fail_one_attempt(proposer, evaluator, mkdiff("c"))
    with pytest.raises(ledger.ProposalRefused) as e:
        propose(proposer, diff_text=mkdiff("d"))
    assert e.value.reason == "already-failed"


def test_ADVERSARIAL_an_invented_weakness_id_is_refused_not_treated_as_new(db, proposer):
    """The second nonce variant, closed by the same lookup.

    `fingerprint()` hashes `weakness_id` verbatim, so inventing one produced a
    brand-new fingerprint and a fresh ceiling. A weakness no source reports has
    no evidence hash to key the ceiling on, so it cannot be proposed against at
    all — which is the honest answer, not a refinement of the hash.
    """
    with pytest.raises(ledger.ProposalRefused) as e:
        propose(proposer, weakness_id="hidden-fee:08-nonce-7")
    assert e.value.reason == "unknown-weakness"
    assert raw(db).execute("SELECT COUNT(*) FROM loop_proposals").fetchone()[0] == 0


def test_the_evidence_sha_on_the_row_is_the_readers_not_the_proposals(db, proposer):
    """Constraint B in miniature: the field that records why an attempt was
    allowed must not be written by the party the attempt belongs to."""
    p = propose(proposer, diff_text=mkdiff("b"))
    stored = raw(db).execute(
        "SELECT weakness_evidence_sha FROM loop_proposals WHERE uuid=?",
        (p["uuid"],)).fetchone()[0]
    assert stored == WEAKNESS_INDEX["hidden-fee:08"]


def test_the_default_weakness_index_reads_the_weakness_reader(db):
    """The injected index above is a TEST double; production must resolve
    through `weaknesses`, the module that DERIVES `evidence_sha`. A gate that
    only ever saw the double would pin the double.

    COMMITTED weaknesses only (B4): the reader deliberately sees uncommitted
    content — observing is its job — but a ceiling key derived from it would be
    proposer-mintable, so the index drops every weakness whose
    `evidence_committed` is False. The full adversarial proof (an uncommitted
    README edit minting a fee) lives in
    test_loop_ratchet_inputs_are_derived.py; what is pinned here is that the
    production index is exactly the reader's committed subset, not a copy that
    could drift."""
    import weaknesses

    index = ledger.default_weakness_index()
    reports = weaknesses.collect()
    committed = {w.weakness_id: w.evidence_sha
                 for r in reports for w in r.weaknesses if w.evidence_committed}
    assert index == committed
    assert index, "the reader reported no weaknesses at all — nothing measured"


def test_the_block_lifts_on_an_operator_forget(db, proposer, evaluator):
    """`nos-loop forget <fp>` — operator identity only (§6.2)."""
    _fail_one_attempt(proposer, evaluator, mkdiff("b"))
    p2 = _fail_one_attempt(proposer, evaluator, mkdiff("c"))
    with pytest.raises(ledger.ProposalRefused):
        propose(proposer, diff_text=mkdiff("d"))

    op = _open("operator")
    try:
        cut = op.forget(raw(db).execute(
            "SELECT fingerprint FROM loop_proposals WHERE uuid=?", (p2["uuid"],)).fetchone()[0])
    finally:
        op.close()
    assert cut["through_proposal_id"] == 2
    assert propose(proposer, diff_text=mkdiff("d"))["attempt_n"] == 1


def test_forget_is_denied_to_the_proposer_and_the_evaluator(db, proposer, evaluator):
    """A loop that can lift its own blocks has no blocks."""
    for led in (proposer, evaluator):
        assert not hasattr(led, "forget")
        with pytest.raises(sqlite3.DatabaseError):
            led._w("INSERT INTO loop_forgets (fingerprint,through_proposal_id,actor) "
                   "VALUES ('f',0,'operator')")


def test_forgets_table_admits_only_the_operator(db):
    ledger.ensure_schema(raw(db))
    with pytest.raises(sqlite3.IntegrityError):
        raw(db).execute("INSERT INTO loop_forgets (fingerprint,through_proposal_id,actor) "
                        "VALUES ('f',0,'agent:remediator')")


# ══════════════════════════════════════════════════════════════════════════
# §5a — gate-add, and other things the ledger derives rather than accepts
# ══════════════════════════════════════════════════════════════════════════

def test_gate_add_is_flagged_requires_operator_by_the_ledger(db, proposer):
    """§5a — a proposal that writes `tests/anatomy/**` is never auto-accepted,
    and the flag is derived from intent_class so the proposer cannot clear it.
    `record_proposal` has no parameter through which it could."""
    # an ADD-only artifact: §5a grants the carve-out to a creation only, so
    # the default modify-shaped mkdiff() would be refused before the flag is
    # ever computed (gate-add-rewrites-gate; test_loop_forget_and_gate_add_adds)
    path = "tests/anatomy/test_new_thing.py"
    p = propose(proposer, intent_class="gate-add", target_paths=[path],
                diff_text=(f"diff --git a/{path} b/{path}\n"
                           f"new file mode 100644\n--- /dev/null\n+++ b/{path}\n"
                           "@@ -0,0 +1 @@\n+def test(): pass\n"))
    assert p["requires_operator"] is True
    row = raw(db).execute("SELECT requires_operator FROM loop_proposals").fetchone()[0]
    assert row == 1
    assert "requires_operator" not in inspect.signature(
        ledger.ProposerLedger.record_proposal).parameters


def test_attempt_number_is_derived_not_supplied(db, proposer, evaluator):
    p1 = _fail_one_attempt(proposer, evaluator, mkdiff("b"))
    p2 = propose(proposer, diff_text=mkdiff("c"))
    assert (p1["attempt_n"], p2["attempt_n"]) == (1, 2)
    assert "attempt_n" not in inspect.signature(
        ledger.ProposerLedger.record_proposal).parameters


# ══════════════════════════════════════════════════════════════════════════
# §11 — a verdict that cannot be replayed is a claim
# ══════════════════════════════════════════════════════════════════════════

def test_a_verdict_carries_everything_needed_to_replay_it(db, proposer, evaluator):
    p = propose(proposer, diff_text=mkdiff("b"))
    v = judge_set(evaluator, [(LINT, 0, LINT_OK), (CODEGEN, 0, CODEGEN_OK)],
                  proposal_uuid=p["uuid"], tree_sha="c" * 40)
    assert v["result"] == "pass"

    rec = evaluator.replay_record(v["uuid"])
    assert rec["tree_sha"] == "c" * 40
    assert {r["judge_name"] for r in rec["runs"]} == {"ansible-lint", "genome-codegen"}
    for r in rec["runs"]:
        assert r["argv"] and r["exit_code"] == 0 and r["stdout_sha"]
    chain = evaluator.verify_chain()
    # `keyed` is environment-dependent (WING_EVENTS_HMAC_SECRET), so it is
    # asserted as a REPORTED FACT rather than pinned to a value — pinning it
    # would make this test pass or fail on the shell that ran it. What is
    # pinned: the mode is always stated, and an unkeyed chain always carries
    # its caveat, because an unkeyed `ok: True` proves consistency and not
    # integrity.
    assert isinstance(chain.pop("keyed"), bool), "verify_chain must report its mode"
    caveat = chain.pop("caveat", None)
    assert chain == {"ok": True, "checked": 1, "broken_uuid": None}
    assert (caveat is None) or ("UNKEYED" in caveat)


def test_history_shows_prior_attempts_and_their_verdicts(db, proposer, evaluator):
    p = _fail_one_attempt(proposer, evaluator, mkdiff("b"))
    fp = raw(db).execute("SELECT fingerprint FROM loop_proposals WHERE uuid=?",
                         (p["uuid"],)).fetchone()[0]
    hist = evaluator.history(fp)
    assert len(hist) == 1
    assert [v["result"] for v in hist[0]["verdicts"]] == ["fail"]
    assert json.loads(hist[0]["target_paths"]) == ["roles/pazny.gitea/defaults/main.yml"]


# ══════════════════════════════════════════════════════════════════════════
# CONSTRAINTS D / E / H — hygiene the ledger must not break
# ══════════════════════════════════════════════════════════════════════════

LEDGER_SRC = (BONE / "ledger.py").read_text(encoding="utf-8")



def test_ledger_mints_no_prefix_derived_credential():
    """Constraint D — the runtime blast radius is 86 and ratcheted. The chain
    key reuses the EXISTING events HMAC secret; nothing new is minted here."""
    for forbidden in ("global_password_prefix", "_pw_"):
        assert forbidden not in LEDGER_SRC, forbidden


def test_ledger_does_not_open_wing_db_directly():
    """Constraint H — the P0.1b single seam. A second connect() is a second
    copy of the path default, which is how drift starts."""
    assert not re.search(r"sqlite3\.connect", code_of(BONE / "ledger.py"))
    assert "from clients import wing" in LEDGER_SRC


def test_ledger_opens_no_socket_and_runs_no_subprocess():
    """Constraint E — this module adds no listener and therefore no edge
    surface; and it is not the judge runner, so it shells out to nothing."""
    code = code_of(BONE / "ledger.py")
    for forbidden in ("subprocess", "socket", "uvicorn", "FastAPI", "APIRouter"):
        assert forbidden not in code, forbidden


#: The committed wing.db schema contract. NOT a second declaration — since
#: 2026-08-29 `bin/export-schema.php` builds it by RUNNING `ledger.ensure_schema()`
#: against a throwaway database, so its loop_* DDL is a rendering of the file
#: below and cannot disagree with it. It had to be added because the artifact
#: called "the wing.db schema" described 41 of the 45 tables that exist, and
#: three gates building fixtures from it had to import `ledger._DDL` themselves.
GENERATED_CONTRACT = REPO / "files/anatomy/skills/contracts/wing.db-schema.sql"


def test_loop_schema_is_declared_in_exactly_one_place():
    """A twin schema drifts. Bone owns these tables; Wing reads them."""
    hits = []
    for f in list((REPO / "files").rglob("*.sql")) + list((REPO / "files").rglob("*.php")):
        if f == GENERATED_CONTRACT:
            continue
        if re.search(r"CREATE TABLE[^;]*loop_verdicts", f.read_text(errors="replace"), re.I):
            hits.append(str(f.relative_to(REPO)))
    assert hits == [], f"loop_* declared outside bone/ledger.py: {hits}"
    assert LEDGER_SRC.count("CREATE TABLE IF NOT EXISTS loop_verdicts") == 1


def test_the_generated_contract_is_generated_and_not_authored():
    """The exemption above has to earn itself, or it is a hole in the rule.

    Two things make the contract a rendering rather than a twin: it says so in
    its own first line, and its loop_* column set is exactly the one
    `ledger._DDL` declares. A hand-edited copy would pass the first check and
    fail the second the moment it drifted, which is the failure the original
    rule exists to prevent.
    """
    body = GENERATED_CONTRACT.read_text(encoding="utf-8")
    assert body.lstrip().startswith("-- AUTO-GENERATED"), (
        "the contract no longer declares itself generated — if it is now "
        "hand-written, it IS a second declaration and the exemption is wrong")

    # Compared by BUILDING both, not by parsing either. A regex over CREATE
    # TABLE text is defeated by whitespace, by a comment containing a comma,
    # and — as the first draft of this proved — by two adjacent tables; sqlite
    # is the only reader of this dialect that cannot be wrong about it.
    def built(apply) -> dict[str, list]:
        conn = sqlite3.connect(":memory:")
        apply(conn)
        return {t: [(c[1], c[2], c[3], c[5]) for c in
                    conn.execute(f"PRAGMA table_info({t})")]
                for t in ("loop_proposals", "loop_verdicts", "loop_judge_runs",
                          "loop_forgets")}

    from_bone = built(ledger.ensure_schema)
    from_contract = built(lambda c: c.executescript(body))
    for table, want in from_bone.items():
        assert from_contract[table] == want, (
            f"{table} in the contract does not match what Bone builds.\n"
            f"  contract: {from_contract[table]}\n  ledger:   {want}\n"
            "Regenerate with `php files/anatomy/wing/bin/export-schema.php "
            "--db=/nonexistent/wing.db`; if that does not fix it, the contract "
            "has been hand-edited and is now a twin.")


def test_worm_triggers_are_created_never_dropped_and_recreated():
    """DROP-then-CREATE (init-db.php's pattern for PRE-EXISTING tables) would
    leave a window in which a concurrent connection sees the verdict table
    unprotected. These tables are new, so IF NOT EXISTS suffices."""
    code = code_of(BONE / "ledger.py")
    assert "DROP TRIGGER" not in code
    assert code.count("CREATE TRIGGER IF NOT EXISTS loop_") == 4
