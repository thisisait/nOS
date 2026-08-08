"""An agent's question may be answered once, and the loser must be told.

WHAT THIS COVERS. `agent_questions` is the write half of the A9 notification
spine (roadmap row `agents-inbox`, filed 2026-08-08 after three independent
technology audits — openworker, cloudflare-os, channels-sdk — converged on the
same missing organ: an agent can broadcast and cannot ASK).

The table has exactly three load-bearing properties, and all three are race
conditions wearing different hats:

  RESOLVE-ONCE            two channels, one answer
  FIRST-RESPONDER-WINS    the loser learns it lost, and what won
  DEADLINE AT ANSWER TIME not swept later, or there is a window in which a
                          question is expired in fact and open in the table

WHY THIS FILE RUNS REAL SQL. The properties above are claims about what SQLite
does when two writers arrive together. A test that read the PHP and asserted the
string `WHERE status='open'` appears would pass against an implementation that
does the check in PHP and the write afterwards — which is precisely the bug the
design exists to avoid. So the schema is executed, and the concurrency is real
rather than described.

The SQL here mirrors AgentQuestionRepository::answer(). That mirroring is itself
checked below: if the repository stops issuing a single conditional UPDATE, the
structural test fails and this file must be re-read, not just re-run.
"""

from __future__ import annotations

import re
import sqlite3
import time
import threading
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCHEMA = REPO / "files/anatomy/wing/db/schema-extensions.sql"
REPOSITORY = REPO / "files/anatomy/wing/app/Model/AgentQuestionRepository.php"
PRESENTER = REPO / "files/anatomy/wing/app/Presenters/Api/InboxPresenter.php"


def _table_sql() -> str:
    """The CREATE TABLE + indexes for agent_questions, alone."""
    src = SCHEMA.read_text(encoding="utf-8")
    start = src.find("CREATE TABLE IF NOT EXISTS agent_questions")
    assert start != -1, "agent_questions is not declared in schema-extensions.sql"
    tail = src[start:]
    end = tail.find("CREATE TABLE", 10)
    return tail if end == -1 else tail[:end]


@pytest.fixture()
def db_path(tmp_path) -> str:
    """A real SQLite file with the real schema.

    The path is resolved ONCE, here. The first draft looked it up inside each
    racing thread via `PRAGMA database_list` on the shared connection; when
    that raised, its thread never reached the barrier and the other waited
    forever. A test that can hang instead of failing is not a test — it is a
    timeout with an opinion.
    """
    path = tmp_path / "wing.db"
    con = sqlite3.connect(path, isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(_table_sql())
    con.close()
    return str(path)


@pytest.fixture()
def db(db_path) -> sqlite3.Connection:
    con = sqlite3.connect(db_path, isolation_level=None, timeout=10)
    yield con
    con.close()


def _ask(con, uuid="q1", token_sha="deadbeef", expires_at=None):
    con.execute(
        "INSERT INTO agent_questions (uuid, agent_name, prompt, reply_token_sha,"
        " status, expires_at, default_on_expiry) VALUES (?,?,?,?,'open',?,?)",
        (uuid, "conductor", "Apply the upgrade?", token_sha, expires_at, "no"),
    )


ANSWER_SQL = (
    "UPDATE agent_questions SET answer=?, answered_by=?, status='answered' "
    "WHERE uuid=? AND reply_token_sha=? AND status='open' "
    "AND (expires_at IS NULL OR expires_at > ?)"
)
FUTURE = "2099-01-01T00:00:00Z"
PAST = "2000-01-01T00:00:00Z"


def _race(db_path: str, pattern: str) -> list[int]:
    """Two writers answer the same question at the same instant.

    Returns their per-writer "I stored an answer" counts, sorted. `conditional`
    is what the repository does; `read_then_write` is the bug it avoids, with a
    50 ms gap standing in for the work PHP does between reading a row and
    writing it back.
    """
    results: list[int] = []
    errors: list[BaseException] = []
    # A barrier timeout, so a thread that dies fails the test instead of
    # hanging the suite. The first draft of this file resolved the DB path
    # INSIDE the threads; when that raised, its thread never reached the
    # barrier and the other waited forever.
    barrier = threading.Barrier(2, timeout=10)

    def worker(who: str) -> None:
        con = sqlite3.connect(db_path, isolation_level=None, timeout=10)
        try:
            barrier.wait()
            if pattern == "conditional":
                cur = con.execute(ANSWER_SQL, (who, who, "q1", "deadbeef", FUTURE))
                results.append(cur.rowcount)
            else:
                row = con.execute(
                    "SELECT status FROM agent_questions WHERE uuid='q1'").fetchone()
                time.sleep(0.05)
                if row[0] == "open":
                    con.execute(
                        "UPDATE agent_questions SET answer=?, answered_by=?,"
                        " status='answered' WHERE uuid='q1'", (who, who))
                    results.append(1)
                else:
                    results.append(0)
        except BaseException as exc:  # noqa: BLE001 — reported, never swallowed
            errors.append(exc)
            barrier.abort()
        finally:
            con.close()

    threads = [threading.Thread(target=worker, args=(f"op{i}",)) for i in (1, 2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not any(t.is_alive() for t in threads), "a racing writer never finished"
    assert not errors, f"a racing writer raised: {errors!r}"
    return sorted(results)


def test_the_naive_pattern_really_does_accept_both_answers(db, db_path):
    """The control, run FIRST, because without it the next test proves nothing.

    Measured while writing this file: with the two writers issuing the naive
    read-then-write back to back, SQLite's own write serialisation made the
    loser's SELECT happen after the winner's commit — so the buggy pattern
    scored [0, 1] too, and the test below passed against BOTH implementations.
    A check that cannot fail is not a check.

    The discriminator is the gap. Any real implementation reads a row, builds
    something from it, and writes later; 50 ms is generous but the shape is
    what matters. With it, the naive pattern accepts BOTH answers — the
    operator who lost is told they decided, and the agent receives whichever
    write landed second.
    """
    _ask(db, uuid="q1")
    assert _race(db_path, "read_then_write") == [1, 1], (
        "the read-then-write control did NOT double-accept, so it cannot "
        "demonstrate the failure the conditional UPDATE prevents. Do not "
        "delete the assertion below on the strength of a control that proved "
        "nothing — find out why SQLite serialised it and model the gap again."
    )


def test_only_one_of_two_simultaneous_answers_lands(db, db_path):
    """The property, against the pattern the control just showed is not free."""
    _ask(db, uuid="q1")
    assert _race(db_path, "conditional") == [0, 1], (
        "expected exactly one writer to win. Two operators answering from two "
        "channels in the same second is the NORMAL case for this table."
    )
    row = db.execute("SELECT status, answer FROM agent_questions WHERE uuid='q1'").fetchone()
    assert row[0] == "answered"
    assert row[1] in ("op1", "op2")


def test_an_expired_question_cannot_be_answered(db):
    """The deadline lives in the WHERE clause, not in a sweeper."""
    _ask(db, uuid="q2", expires_at=PAST)
    cur = db.execute(ANSWER_SQL, ("late", "late", "q2", "deadbeef", FUTURE))
    assert cur.rowcount == 0, (
        "an answer landed on a question whose deadline had passed. The agent "
        "has already proceeded with default_on_expiry, so this answer would be "
        "recorded against a decision that was never taken."
    )


def test_a_wrong_token_cannot_answer(db):
    _ask(db, uuid="q3")
    cur = db.execute(ANSWER_SQL, ("x", "x", "q3", "notthetoken", FUTURE))
    assert cur.rowcount == 0


def test_the_repository_issues_one_conditional_update(db):
    """Structural twin of the race test.

    The SQL above only proves SQLite behaves; this proves the repository asks
    it to. A read-then-write implementation would pass every runtime test in
    this file while being exactly the bug.
    """
    src = REPOSITORY.read_text(encoding="utf-8")
    body = src[src.find("public function answer") : src.find("public function poll")]
    assert "->update([" in body, "answer() no longer issues an UPDATE"
    for precondition in ("'status', 'open'", "reply_token_sha", "expires_at"):
        assert precondition in body, (
            f"answer()'s UPDATE no longer carries `{precondition}` as a "
            "precondition. Every condition must ride in the WHERE clause — "
            "checking in PHP and writing afterwards accepts both racers."
        )
    assert re.search(r"\$affected\s*===?\s*1", body), (
        "answer() does not branch on the affected-row count. That count IS the "
        "verdict; without it the method cannot tell winning from losing."
    )


def test_a_lost_race_is_reported_as_conflict_not_success():
    """A reply that silently evaporates is worse than one that is refused."""
    src = PRESENTER.read_text(encoding="utf-8")
    body = src[src.find("public function actionAnswer") : src.find("public function actionCancel")]
    assert body.count("S409_Conflict") >= 2, (
        "InboxPresenter::actionAnswer does not return 409 for both "
        "already-answered and expired. Reporting a lost race as 200 tells the "
        "operator they decided something when they did not."
    )
    assert "answered_by" in body and "answer'" in body, (
        "the 409 does not carry the answer that won. 'Too late' sends the "
        "operator to go and look; the row already knows what was decided."
    )


def test_a_question_is_never_quieter_than_high():
    """The ask itself is always something a human must see.

    NotificationRepository routes to ntfy only at high/critical. An `info`
    question would be one unread row in a web inbox while a run blocks — the
    same failure that map's own docblock records from the Pulse path.
    """
    src = PRESENTER.read_text(encoding="utf-8")
    assert "'high'" in src and "in_array($severity, ['critical', 'high'], true)" in src, (
        "InboxPresenter no longer floors a question's notification severity at "
        "high. The severity an agent declares describes what it is asking "
        "ABOUT; the asking is always urgent."
    )


def test_a_deadline_requires_a_stated_default():
    """A timeout with no declared default picks an outcome nobody wrote down."""
    src = REPOSITORY.read_text(encoding="utf-8")
    ask = src[src.find("public function ask") : src.find("public function answer")]
    assert "default_on_expiry" in ask and "InvalidArgumentException" in ask, (
        "ask() accepts a ttl without requiring default_on_expiry. The run will "
        "then do SOMETHING when nobody answers and nothing will record what."
    )


def test_the_token_is_stored_hashed_and_never_returned_in_a_list():
    src = REPOSITORY.read_text(encoding="utf-8")
    assert "hash('sha256', $token)" in src, (
        "the reply token is not hashed at rest. A question list is readable by "
        "any Tier-1 caller; a plaintext token there is a bearer credential "
        "handed to every reader."
    )
    pub = src[src.find("public function public") :][:400]
    assert "unset($row['reply_token_sha'])" in pub, (
        "public() no longer strips reply_token_sha — the hash must not leave "
        "the repository either."
    )
