"""The expired count must include the rows nothing swept, or it reads zero forever.

WHAT /questions IS FOR. Wing's /inbox shows the open queue and answers it. The
ledger at /questions adds the part no other surface reports: how often a
question reached its deadline with nobody there — the loop deciding without the
operator, on whatever default the agent declared.

WHY THIS IS EASY TO GET WRONG, and why the gate executes SQL instead of reading
the PHP. `agent_questions` HAS NO SWEEPER — by design, because a sweeper leaves
a window in which a question is expired in fact and open in the table. The only
writer of `status='expired'` is an answer that arrived too late. So a count
phrased as `WHERE status='expired'` is not merely approximate: on an estate
where nobody answers late, it is zero forever, and the surface built to say the
operator was outrun would report that they never were.

So the condition is lifted out of `AgentQuestionRepository::countExpired()` and
run against a real SQLite carrying the real schema and a row of every shape. A
test asserting the source contains the string `expires_at` would pass against
the broken query too.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCHEMA = REPO / "files/anatomy/wing/db/schema-extensions.sql"
REPOSITORY = REPO / "files/anatomy/wing/app/Model/AgentQuestionRepository.php"
PRESENTER = REPO / "files/anatomy/wing/app/Presenters/QuestionsPresenter.php"
TEMPLATE = REPO / "files/anatomy/wing/app/Templates/Questions/default.latte"
ROUTER = REPO / "files/anatomy/wing/app/Core/RouterFactory.php"

NOW = "2026-08-28T12:00:00Z"
PAST = "2026-08-28T11:00:00Z"
FUTURE = "2099-01-01T00:00:00Z"


def _table_sql() -> str:
    src = SCHEMA.read_text(encoding="utf-8")
    start = src.find("CREATE TABLE IF NOT EXISTS agent_questions")
    assert start != -1, "agent_questions is not declared in schema-extensions.sql"
    tail = src[start:]
    end = tail.find("CREATE TABLE", 10)
    return tail if end == -1 else tail[:end]


def _method_body(name: str) -> str:
    src = REPOSITORY.read_text(encoding="utf-8")
    m = re.search(rf"public function {name}\(.*?\n\t\}}", src, re.S)
    assert m, f"AgentQuestionRepository::{name} not parseable — has it been renamed?"
    return m.group(0)


def _count_expired_query() -> tuple[str, list[str]]:
    """The WHERE the shipped code issues, plus the params it binds.

    Lifted from the artifact rather than restated here: a gate holding its own
    copy of the condition passes whatever the repository does.
    """
    body = _method_body("countExpired")
    call = re.search(r"->where\(\s*(.+?)\s*\)\s*(?:->count|;)", body, re.S)
    assert call, "countExpired() no longer issues a ->where(...) — re-read this file"
    args = call.group(1)

    cond = re.match(r'\s*["\'](.+?)["\']\s*,', args, re.S)
    assert cond, "countExpired()'s where() has no literal condition string"
    # gmdate('Y-m-d\TH:i:s\Z') carries a quoted format string of its own; it is
    # one bound param (the clock), not two.
    rest = re.sub(r"gmdate\([^)]*\)", "@NOW@", args[cond.end():])
    params: list[str] = []
    for tok in re.finditer(r"'([^']*)'|@NOW@", rest):
        params.append(NOW if tok.group(0) == "@NOW@" else tok.group(1))
    return cond.group(1), params


@pytest.fixture()
def db(tmp_path) -> sqlite3.Connection:
    con = sqlite3.connect(tmp_path / "wing.db", isolation_level=None)
    con.executescript(_table_sql())
    rows = [
        # (uuid, status, expires_at)  — one of every shape the table holds
        ("open-no-deadline", "open", None),      # waiting, forever, patiently
        ("open-not-yet-due", "open", FUTURE),    # waiting, still in time
        ("open-past-due", "open", PAST),         # EXPIRED IN FACT, unswept
        ("swept-expired", "expired", PAST),      # answered too late, so marked
        ("answered", "answered", PAST),          # answered in time; deadline moot
        ("cancelled", "cancelled", PAST),        # agent withdrew it
    ]
    for uuid, status, exp in rows:
        con.execute(
            "INSERT INTO agent_questions (uuid, agent_name, prompt,"
            " reply_token_sha, status, expires_at, default_on_expiry)"
            " VALUES (?,?,?,?,?,?,'refuse')",
            (uuid, "conductor", "Apply the upgrade?", "sha", status, exp),
        )
    yield con
    con.close()


def _count(con: sqlite3.Connection, where: str, params: list[str]) -> int:
    return con.execute(
        f"SELECT COUNT(*) FROM agent_questions WHERE {where}", params
    ).fetchone()[0]


def test_the_count_includes_the_unswept_expiry(db):
    """Two rows are expired: the one marked so, and the one nothing marked."""
    where, params = _count_expired_query()
    assert _count(db, where, params) == 2, (
        "countExpired() disagrees with the table. Expected both `swept-expired` "
        "and `open-past-due` — the second is the whole point: nothing sweeps "
        "agent_questions, so an unanswered question keeps saying `open`."
    )


def test_the_naive_count_is_the_bug_this_gate_exists_for(db):
    """The condition the gate refuses, run against the same rows.

    Stated as an executed comparison rather than a comment so the failure mode
    is visible: swept-only counting reports ONE where the truth is two, and on
    an estate where no answer ever arrives late it reports zero.
    """
    where, params = _count_expired_query()
    assert _count(db, "status = 'expired'", []) < _count(db, where, params), (
        "countExpired() has collapsed to counting status='expired' — the value "
        "only a late answer ever writes."
    )


def test_open_and_answered_rows_are_not_counted_as_expired(db):
    """A question still in time, or answered, or withdrawn, is not an outrun."""
    where, params = _count_expired_query()
    ids = {
        r[0] for r in db.execute(
            f"SELECT uuid FROM agent_questions WHERE {where}", params
        )
    }
    assert ids == {"open-past-due", "swept-expired"}, (
        f"countExpired() selects the wrong rows: {sorted(ids)}. An overstated "
        "expiry number is as bad as an understated one — it tells the operator "
        "the loop ran away when it did not."
    )


def test_the_ledger_resolves_expiry_at_read_time(db):
    """listRecent() must apply the same deadline rule poll() does.

    Without it the table's `status` column is reprinted verbatim and a queue
    nobody attended renders as `open`, i.e. as attended-and-waiting.
    """
    body = _method_body("listRecent")
    assert "isPastDeadline(" in body and "'expired'" in body, (
        "listRecent() prints the status column raw — a past-deadline row would "
        "render as open."
    )
    assert "$this->public(" in body, (
        "listRecent() returns rows without public() — reply_token_sha is a "
        "credential and does not leave the repository."
    )


def test_the_ledger_cannot_decide_anything():
    """/questions is read-only. Answering stays on /inbox, which is where the
    resolve-once UPDATE, the forward-auth identity and the CSRF gate live. A
    verb here would be a second decision path over the same rows."""
    src = PRESENTER.read_text(encoding="utf-8")
    actions = re.findall(r"public function (action\w+)", src)
    assert actions == [], f"QuestionsPresenter grew mutating actions: {actions}"
    tmpl = TEMPLATE.read_text(encoding="utf-8")
    assert "<form" not in tmpl, (
        "the questions template posts something — the answering path belongs to "
        "/inbox"
    )
    assert re.search(r"addRoute\('questions',\s*'Questions:default'\)",
                     ROUTER.read_text(encoding="utf-8")), (
        "no /questions route — Nette renders an unroutable page as a 404 the "
        "nav tab still links to"
    )
