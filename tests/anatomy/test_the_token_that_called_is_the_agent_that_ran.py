"""Every agent on the ops plane presents its OWN Wing principal, and that
principal is narrower than the operator's.

THE DEFECT. `roles/pazny.wing/tasks/post.yml` has provisioned a named
`api_tokens` row per agent since A8 — conductor, librarian, surveyor,
upgrade-architect — and `BaseApiPresenter::getActorId()` writes that row's
`name` onto every write as `actor_id`. The apparatus for per-agent attribution
was complete. It was also unreached from the CLI path: `tools/run-agent.sh`
exports the RUNNING Wing job's whole environment (deliberately — see its
header), which includes the operator's `WING_API_TOKEN`, and `McpWingTool`
read exactly that variable. So a supervised run signed the operator's name to
the agent's work, and `events.actor_id` said `ansible-provisioned` for every
one of them. Nothing was broken; nothing was attributable either.

WHAT THIS FILE PINS, in the order the request travels:

1. `TokenRepository::permits()` — the decision, exercised for real in PHP over
   the whole matrix, including the two directions that matter: a read-scoped
   token REFUSED on a write, and an unscoped (legacy) token still admitted.
   The second is not a courtesy: defaulting the incumbents closed would 403
   the estate on the converge that adds the column.

2. `BaseApiPresenter::startup()` — that the decision is actually consulted,
   and that its refusal is 403 and not 401. A 401 tells a correctly
   authenticated caller to re-authenticate, which it cannot fix.

3. `api_tokens.scopes` reaches a PRE-EXISTING database. Built by running the
   real `bin/init-db.php` against a legacy-shaped table, because a column
   declared only in the CREATE is a column no live wing.db ever gets —
   `CREATE TABLE IF NOT EXISTS` is a no-op there, which is the exact failure
   the file's own row_hash comment records.

4. The reader: for every agent session, the events it owns must carry the
   agent's own name. Run against the FIXED fixture and against the broken one
   — a reader that cannot see the defect it was written for is not a reader.
"""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
WING = REPO / "files/anatomy/wing"
TOKEN_REPO = WING / "app/Model/TokenRepository.php"
BASE_PRESENTER = WING / "app/Presenters/Api/BaseApiPresenter.php"
INIT_DB = WING / "bin/init-db.php"

php_only = pytest.mark.skipif(
    shutil.which("php") is None, reason="php not installed on this runner"
)


def code_only(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"^\s*//.*$", "", src, flags=re.M)


# ── 1. the decision ──────────────────────────────────────────────────────────

# (scopes, method, expected). `None` is the legacy row every existing token has.
MATRIX = [
    (None, "GET", True),
    (None, "POST", True),
    ("", "POST", True),
    ("wing.read", "GET", True),
    ("wing.read", "HEAD", True),
    ("wing.read", "POST", False),
    ("wing.read", "DELETE", False),
    ("wing.read", "PUT", False),
    ("wing.read,wing.write", "POST", True),
    ("wing.write", "GET", True),
    ("wing.write", "POST", True),
    (" wing.read , wing.write ", "POST", True),
    ("cortex.get", "GET", False),
    ("cortex.get", "POST", False),
]


@php_only
def test_a_read_scoped_token_is_refused_on_a_write():
    """Loads the class and calls it. A grep would pass against a body that
    returns true unconditionally, which is precisely the shape a hurried
    'unblock the converge' edit produces."""
    script = (
        f"require '{TOKEN_REPO}';\n"
        "$out = [];\n"
        "foreach (json_decode(file_get_contents('php://stdin'), true) as $c) {\n"
        "  $out[] = App\\Model\\TokenRepository::permits($c[0], $c[1]);\n"
        "}\n"
        "echo json_encode($out);\n"
    )
    proc = subprocess.run(
        ["php", "-r", script],
        input=json.dumps([[s, m] for s, m, _ in MATRIX]),
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, f"php refused to load TokenRepository:\n{proc.stderr}"
    got = json.loads(proc.stdout)
    wrong = [
        f"scopes={s!r} {m} -> {g} (want {w})"
        for (s, m, w), g in zip(MATRIX, got) if g != w
    ]
    assert not wrong, (
        "TokenRepository::permits() decides the ops plane's route class "
        "wrongly:\n  " + "\n  ".join(wrong)
        + "\n\nA read-scoped token that passes a write is the whole point of "
        "the column; an unscoped one that fails a write 403s every legacy "
        "token on the converge that adds it."
    )


# ── 2. the enforcement site ──────────────────────────────────────────────────

def _startup_body() -> str:
    code = code_only(BASE_PRESENTER.read_text(encoding="utf-8"))
    m = re.search(
        r"public function startup\(\)\s*:\s*void\s*\{(.*?)\n\t\}", code, re.S
    )
    assert m, "BaseApiPresenter::startup() body not parseable"
    return m.group(1)


def test_the_scope_check_runs_on_every_authenticated_request():
    body = _startup_body()
    assert re.search(r"TokenRepository::permits\s*\(", body), (
        "BaseApiPresenter::startup() no longer consults "
        "TokenRepository::permits(). The column then records an intent "
        "nothing enforces — a scope that is documented and unchecked is "
        "worse than none, because it reads as protection."
    )
    assert "scopes" in body, (
        "startup() calls permits() without passing the validated token's "
        "`scopes` — the check is running against something else."
    )
    # Ordering: the scope check is meaningless before the token is validated.
    assert body.index("requireTokenAuth") < body.index("TokenRepository::permits"), (
        "the scope check runs BEFORE requireTokenAuth() — it would read "
        "$validatedToken while it is still null, which permits() treats as "
        "unscoped, i.e. allows everything."
    )


def test_the_refusal_is_403_and_not_401():
    body = _startup_body()
    m = re.search(r"permits\s*\(.*?\)\s*\)\s*\{(.*?)\n\t\t\}", body, re.S)
    assert m, "the permits() refusal branch is not parseable"
    branch = m.group(1)
    assert "403" in branch or "S403_Forbidden" in branch, (
        "a scope refusal answers with something other than 403. The caller "
        "authenticated correctly and is not permitted; 401 tells it to "
        "retry the one thing that already worked."
    )


# ── 3. the column reaches a pre-existing database ────────────────────────────

LEGACY_API_TOKENS = """
CREATE TABLE api_tokens (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    token       TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL DEFAULT 'default',
    created_by  TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    last_used_at TEXT,
    active      INTEGER NOT NULL DEFAULT 1
);
"""


def _columns(db: Path, table: str) -> set[str]:
    con = sqlite3.connect(db)
    try:
        return {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
    finally:
        con.close()


@php_only
def test_the_scopes_column_reaches_an_existing_database(tmp_path):
    """The estate's wing.db already exists. A column added only to the CREATE
    would never appear there, and every scoped provision would fail on
    `no such column: scopes` — after the converge had already reported the
    token written."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    con = sqlite3.connect(data_dir / "wing.db")
    con.executescript(LEGACY_API_TOKENS)
    con.commit()
    con.close()

    proc = subprocess.run(
        ["php", str(INIT_DB), f"--data-dir={data_dir}"],
        capture_output=True, text=True, timeout=180, cwd=str(WING),
    )
    assert proc.returncode == 0, f"init-db.php failed:\n{proc.stdout}\n{proc.stderr}"
    cols = _columns(data_dir / "wing.db", "api_tokens")
    assert "scopes" in cols, (
        "bin/init-db.php's ALTER sweep does not add api_tokens.scopes to a "
        f"pre-existing database (columns: {sorted(cols)}). CREATE TABLE IF "
        "NOT EXISTS is a no-op on every live wing.db."
    )


# ── 4. the reader ────────────────────────────────────────────────────────────

FIXTURE = """
CREATE TABLE api_tokens (id INTEGER PRIMARY KEY, name TEXT, scopes TEXT);
CREATE TABLE agent_sessions (uuid TEXT PRIMARY KEY, agent_name TEXT);
CREATE TABLE events (id INTEGER PRIMARY KEY, type TEXT, actor_id TEXT,
                     actor_action_id TEXT);
INSERT INTO api_tokens (name, scopes) VALUES
    ('ansible-provisioned', NULL),
    ('surveyor', 'wing.read'),
    ('librarian', 'wing.read,wing.write');
INSERT INTO agent_sessions VALUES
    ('11111111-1111-1111-1111-111111111111', 'surveyor'),
    ('22222222-2222-2222-2222-222222222222', 'librarian');
"""

FIXED = """
INSERT INTO events (type, actor_id, actor_action_id) VALUES
    ('agent_tool_use', 'surveyor',  '11111111-1111-1111-1111-111111111111'),
    ('agent_message',  'surveyor',  '11111111-1111-1111-1111-111111111111'),
    ('agent_tool_use', 'librarian', '22222222-2222-2222-2222-222222222222');
"""

# What the estate actually recorded: every agent borrowing the operator's
# bearer out of the daemon environment.
BROKEN = """
INSERT INTO events (type, actor_id, actor_action_id) VALUES
    ('agent_tool_use', 'ansible-provisioned', '11111111-1111-1111-1111-111111111111'),
    ('agent_message',  'ansible-provisioned', '11111111-1111-1111-1111-111111111111'),
    ('agent_tool_use', 'ansible-provisioned', '22222222-2222-2222-2222-222222222222');
"""


def misattributed(db: Path) -> list[tuple[str, str, str]]:
    """(session_uuid, agent that ran, token name that got recorded) for every
    event whose recorded principal is not the owning session's agent.

    Reads the store, decides nothing about what it finds — an event owned by
    no session is not this reader's business, so the join is inner.
    """
    con = sqlite3.connect(db)
    try:
        return con.execute(
            """
            SELECT s.uuid, s.agent_name, e.actor_id
              FROM events e
              JOIN agent_sessions s ON s.uuid = e.actor_action_id
             WHERE e.actor_id IS NOT s.agent_name
             ORDER BY e.id
            """
        ).fetchall()
    finally:
        con.close()


def _fixture(tmp_path: Path, events_sql: str, name: str) -> Path:
    db = tmp_path / name
    con = sqlite3.connect(db)
    con.executescript(FIXTURE + events_sql)
    con.commit()
    con.close()
    return db


def test_the_reader_sees_the_shared_token(tmp_path):
    """Run against the BROKEN state first. A reader only checked against the
    fixed one passes by being blind."""
    found = misattributed(_fixture(tmp_path, BROKEN, "broken.db"))
    assert len(found) == 3, (
        "the reader does not notice three agent events signed with the "
        f"operator's token: {found}"
    )
    assert {row[2] for row in found} == {"ansible-provisioned"}


def test_every_agent_event_names_the_agent_that_ran(tmp_path):
    found = misattributed(_fixture(tmp_path, FIXED, "fixed.db"))
    assert not found, (
        "an agent session's events are recorded under a token that is not "
        f"the agent's own: {found}"
    )


def test_each_session_agent_has_a_principal_of_its_own(tmp_path):
    """The attribution above only holds while each agent HAS a token row named
    after it — otherwise the operator's bearer is the only one it can present,
    and the borrowing is forced rather than accidental."""
    db = _fixture(tmp_path, FIXED, "roster.db")
    con = sqlite3.connect(db)
    try:
        agents = {r[0] for r in con.execute("SELECT agent_name FROM agent_sessions")}
        principals = {r[0] for r in con.execute("SELECT name FROM api_tokens")}
    finally:
        con.close()
    assert agents <= principals, (
        f"agents with no api_tokens row of their own: {sorted(agents - principals)}"
    )


# ── 5. the runtime end: which variable the tool reads ────────────────────────

def test_the_wing_tool_prefers_the_agents_own_token():
    src = code_only((WING / "app/AgentKit/Tools/McpWingTool.php").read_text(encoding="utf-8"))
    assert "NOS_AGENT_WING_TOKEN" in src, (
        "McpWingTool no longer reads NOS_AGENT_WING_TOKEN — it is back to "
        "presenting whatever WING_API_TOKEN the daemon environment carried, "
        "which on the CLI path is the operator's admin bearer."
    )
    assert src.index("NOS_AGENT_WING_TOKEN") < src.index("WING_API_TOKEN"), (
        "WING_API_TOKEN is consulted before NOS_AGENT_WING_TOKEN. The "
        "operator token is always present on a supervised run, so it would "
        "always win and the per-agent principal would never be used."
    )
    assert re.search(r"error_log\(\s*\n?\s*'\[mcp-wing\] WARN", src), (
        "the fallback to the operator token is silent. It is allowed (a "
        "pre-converge estate has no per-agent secret yet) precisely because "
        "it announces itself; unannounced it is the original defect."
    )


def test_the_runner_mints_the_agents_token():
    src = (REPO / "tools/run-agent.sh").read_text(encoding="utf-8")
    assert "NOS_AGENT_WING_TOKEN" in src and "_wing_api_token" in src, (
        "tools/run-agent.sh no longer resolves the per-agent Wing bearer "
        "from ~/.nos/secrets.yml — nothing else on the CLI path can, and "
        "the export loop above it hands the agent the operator's token."
    )
