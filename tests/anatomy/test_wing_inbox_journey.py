"""One journey through Wing's inbox: questions, answers, approvals, notifications, filed reports.

Absorbed (2026-11-08, roadmap gate-diet-role-journeys); every assert kept verbatim:
  test_the_face_inbox_answers_once            -> section "face inbox"
  test_a_notification_reaches_who_it_names    -> section "notification address"
  test_a_report_arrives_with_its_body         -> section "report body"
  test_the_questions_ledger_counts_the_unswept -> section "questions ledger"
  test_an_empty_identity_is_refused           -> section "empty identity"
  test_approval_queue_event_backed            -> section "approval queue"
  test_a_question_notification_carries_a_click -> section "question click"

PHP gates read code with comments stripped (_php_code) — four gates for this
area once failed against correct code by matching their own prose.
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
APP = WING / "app"
AUTOLOAD = WING / "vendor/autoload.php"
PRESENTERS = APP / "Presenters"
ROUTER = APP / "Core/RouterFactory.php"
REPOSITORY = APP / "Model/AgentQuestionRepository.php"
FUTURE = "2099-01-01T00:00:00Z"

needs_php = pytest.mark.skipif(not shutil.which("php"), reason="php runs Wing")
needs_vendor = pytest.mark.skipif(not AUTOLOAD.exists(), reason="wing vendor/autoload.php missing (composer install)")


def _php_code(src: str) -> str:
    """PHP source with block and line comments removed."""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"^\s*//.*$", "", src, flags=re.M)


# This tree's app/, even with vendor symlinked from another checkout.
_AUTOLOAD_PRELUDE = r"""
$composer = require $argv[1];
$home = dirname(realpath($argv[1]), 2);
spl_autoload_register(function ($c) use ($composer, $home) {
  $own = getcwd() . '/app/' . str_replace('\\', '/', substr($c, 4)) . '.php';
  $f = realpath((string) $composer->findFile($c));
  if (str_starts_with($c, 'App\\') && is_file($own)) require $own;
  elseif ($f && str_starts_with($f, $home . '/app/')) require getcwd() . substr($f, strlen($home));
}, prepend: true);
"""


# ── face inbox ───────────────────────────────────────────────────────────────
# Row wing-inc1-inbox-app (2026-11-08): the face BFF speaks for a person; Wing decides the
# tier itself, the record names the edge identity (user:<uid>, via face), a lost race is a
# 409 naming the winner. Real presenters + SQLite, like test_the_inbox_answers_once.py.

_INBOX_HARNESS = _AUTOLOAD_PRELUDE + r"""
$pdo = new Nette\Database\Connection('sqlite:' . $argv[2]);
$pdo->query('INSERT INTO api_tokens', ['token' => hash('sha256', 'bff'), 'name' => 'face-bff', 'scopes' => 'wing.operator,wing.write', 'active' => 1]);
$cache = new Nette\Caching\Storages\DevNullStorage;
$structure = new Nette\Database\Structure($pdo, $cache);
$db = new Nette\Database\Explorer($pdo, $structure, new Nette\Database\Conventions\DiscoveredConventions($structure), $cache);
$events = new App\Model\EventRepository($db);
$notes = new App\Model\NotificationRepository($db);
$questions = new App\Model\AgentQuestionRepository($db, $events, $notes);
$out = [];
foreach (json_decode($argv[3], true) as $c) {
  $cls = 'App\\Presenters\\Api\\' . $c['presenter'] . 'Presenter';
  $p = $c['presenter'] === 'Inbox' ? new $cls($questions) : new $cls($notes);
  $p->tokenRepo = new App\Model\TokenRepository($db);
  $p->autoCanonicalize = false;
  $headers = ['authorization' => 'Bearer bff', 'x-nos-user-uid' => 'alice', 'x-nos-user-groups' => $c['groups']];
  $req = new Nette\Http\Request(new Nette\Http\UrlScript('http://wing/api'), headers: $headers,
    method: $c['method'], rawBodyCallback: fn () => json_encode($c['body'] ?? []));
  $res = new Nette\Http\Response;
  $p->injectPrimary($req, $res);
  $r = $p->run(new Nette\Application\Request('Api:' . $c['presenter'], $c['method'], ['action' => $c['action']] + ($c['params'] ?? [])));
  $payload = $r instanceof Nette\Application\Responses\JsonResponse ? $r->getPayload() : null;
  $out[] = ['code' => $res->getCode(), 'payload' => $payload];
}
$row = $pdo->fetch("SELECT status, answer, answered_by, answered_via FROM agent_questions WHERE uuid = 'q-face'");
$out[] = ['row' => (array) $row, 'read' => $pdo->fetchField("SELECT wing_inbox_read_at FROM notifications WHERE uuid = 'n-face'")];
echo json_encode($out);
"""


@needs_php
@needs_vendor
def test_a_tier_one_face_person_answers_once_and_reads_once(tmp_path):
    subprocess.run(["php", str(WING / "bin/init-db.php"), f"--data-dir={tmp_path}"], capture_output=True, check=True, timeout=60)
    con = sqlite3.connect(tmp_path / "wing.db", isolation_level=None)
    con.execute("INSERT INTO agent_questions (uuid, agent_name, kind, prompt, reply_token_sha, status, expires_at, default_on_expiry)"
                " VALUES ('q-face', 'conductor', 'approval', 'Apply the upgrade?', 'a-token-the-face-never-holds', 'open', ?, 'no')",
                (FUTURE,))
    con.execute("INSERT INTO agent_questions (uuid, agent_name, kind, prompt, reply_token_sha, status, expires_at, default_on_expiry)"
                " VALUES ('q-other', 'conductor', 'approval', 'Rotate the key?', 'sha-of-a-secret-token', 'open', ?, 'no')",
                (FUTURE,))
    con.execute("INSERT INTO notifications (uuid, severity, title) VALUES ('n-face', 'high', 'Gitleaks: 5 new findings')")
    con.close()

    admin, user = "nos-admins", "nos-users"

    def answer(a: str, groups: str) -> dict:
        return {"presenter": "Inbox", "action": "answer", "method": "POST", "groups": groups,
                "params": {"uuid": "q-face"}, "body": {"answer": a, "answered_by": "someone-else"}}

    def read(groups: str) -> dict:
        return {"presenter": "Notifications", "action": "read", "method": "POST", "groups": groups, "params": {"uuid": "n-face"}}
    cases = [answer("no", user), answer("yes", admin), answer("no", admin),
             {"presenter": "Inbox", "action": "questions", "method": "GET", "groups": admin},
             {"presenter": "Inbox", "action": "questions", "method": "GET", "groups": user},
             {"presenter": "Inbox", "action": "questions", "method": "POST", "groups": admin,
              "body": {"agent_name": "x", "prompt": "self-ask"}},
             read(user), read(admin), read(admin)]
    r = subprocess.run(["php", "-d", "error_reporting=E_ALL", "-r", _INBOX_HARNESS, str(AUTOLOAD), str(tmp_path / "wing.db"), json.dumps(cases)],
                       capture_output=True, text=True, timeout=120, cwd=WING, check=False)
    assert r.returncode == 0, r.stdout + r.stderr
    got = json.loads(r.stdout)
    assert got[0]["code"] == 403, f"a Tier-3 face person answered: {got[0]}"
    assert got[1]["code"] == 200 and got[1]["payload"]["result"] == "ok", got[1]
    assert got[2]["code"] == 409 and got[2]["payload"]["answer"] == "yes", f"the second answer must lose: {got[2]}"
    assert got[3]["code"] == 200, f"a Tier-1 face person lists the questions: {got[3]}"
    listed = json.dumps(got[3]["payload"])
    assert "Rotate the key?" in listed, f"the open question is not listed: {listed}"
    assert "reply_token" not in listed and "sha-of-a-secret-token" not in listed, "a list carried the reply token"
    assert got[4]["code"] == 403, f"a Tier-3 face person listed the questions: {got[4]}"
    assert got[5]["code"] == 403, f"the face asked a question as an agent: {got[5]}"
    assert got[6]["code"] == 403, f"a Tier-3 face person marked a notification read: {got[6]}"
    assert got[7]["code"] == 200 and got[8]["code"] == 404, f"read once, then said so: {got[7]} {got[8]}"
    # The body cannot name someone else: the person is the edge identity.
    assert got[9]["row"] == {"status": "answered", "answer": "yes", "answered_by": "user:alice", "answered_via": "face"}, got[9]
    assert got[9]["read"], "the notification was not marked read"


# ── notification address ─────────────────────────────────────────────────────
# 2026-08-08: target_actor_id existed but no transport read it, so mail for agent:librarian
# went silently to the operator. An unroutable address must FAIL, never fall back; and
# fetch_pending() must SELECT the column, or `?? 'operator'` hides the missing field.

DISPATCH = WING / "bin/dispatch-notifications.php"


def function_body(name: str) -> str:
    """One function, sliced to the NEXT top-level definition."""
    s = _php_code(DISPATCH.read_text(encoding="utf-8"))
    start = s.find(f"function {name}(")
    assert start != -1, f"{name}() is gone — re-point this gate"
    nxt = re.search(r"\nfunction \w+\(", s[start + 1:])
    body = s[start : start + 1 + nxt.start()] if nxt else s[start:]
    assert len(body) > 120, f"{name}() slice is implausibly short ({len(body)})"
    return body


def test_the_column_is_actually_selected():
    """Routing that reads an unfetched column silently routes to the default."""
    fetch = function_body("fetch_pending")
    assert "target_actor_id" in fetch, (
        "fetch_pending() does not SELECT target_actor_id, so every row arrives "
        "without it and `?? 'operator'` sends everything to the operator — the "
        "exact defect the routing was written to fix, reintroduced invisibly."
    )


def test_ntfy_routes_by_recipient_not_only_severity():
    body = function_body("ntfy_topic_for")
    assert "target_actor_id" in body, (
        "the ntfy topic no longer depends on the recipient."
    )
    assert "severity" in body, (
        "the operator's topic must stay `nos-<severity>` — that is the "
        "subscription already on the phone and the volume control the operator "
        "asked for."
    )
    deliver = function_body("deliver_ntfy")
    assert "ntfy_topic_for(" in deliver, (
        "deliver_ntfy no longer asks ntfy_topic_for() which topic to use."
    )


def test_an_unroutable_mail_target_fails_instead_of_falling_back():
    body = function_body("deliver_mail")
    assert "target_actor_id" in body, (
        "deliver_mail ignores target_actor_id again, so mail for any actor "
        "goes to the operator address."
    )
    # The failure must be a RETURNED error string — that is what mark_dispatched
    # records and what makes the row visibly undelivered.
    assert re.search(r"return\s+\"no mail route", body), (
        "an unroutable target does not return an error. Silently delivering to "
        "the operator, or silently skipping, are both the original defect."
    )
    assert "$recipient" in body, "the operator path no longer sends anywhere"


def test_the_operator_default_is_explicit_everywhere():
    """`operator` is a bare string; both call sites normalise it the same way."""
    for fn in ("ntfy_topic_for", "deliver_mail"):
        body = function_body(fn)
        assert "'operator'" in body, f"{fn}() has no explicit operator case"
        assert "trim(" in body, (
            f"{fn}() does not trim target_actor_id, so ' operator' and "
            "'operator' would route differently."
        )


# ── report body ──────────────────────────────────────────────────────────────
# Measured 2026-08-29, session 461db38c: insert() read `result`, every agent prompt sends
# `result_json`, so a full survey was stored empty and the run counted as satisfied.
# Both spellings are inserted through the real repository and the real reader is RUN.

needs_report_vendor = pytest.mark.skipif(
    not AUTOLOAD.is_file(),
    reason="php binary or wing vendor/autoload.php missing — run `composer "
           "install` in files/anatomy/wing",
)

PROBE = r"""
require __DIR__ . '/vendor/autoload.php';

use App\Model\EventRepository;
use Nette\Database\Connection;
use Nette\Database\Explorer;
use Nette\Database\Structure;
use Nette\Database\Conventions\DiscoveredConventions;
use Nette\Caching\Storages\MemoryStorage;

$db = sys_get_temp_dir() . '/nos-events-' . bin2hex(random_bytes(4)) . '.db';
$init = getenv('NOS_INIT_DB');
exec(sprintf('php %s --data-dir=%s 2>&1', escapeshellarg($init), escapeshellarg(dirname($db))), $o, $rc);
// init-db writes wing.db in the given dir; use that.
$db = dirname($db) . '/wing.db';

$conn = new Connection('sqlite:' . $db);
$storage = new MemoryStorage();
$structure = new Structure($conn, $storage);
$explorer = new Explorer($conn, $structure, new DiscoveredConventions($structure), $storage);
$repo = new EventRepository($explorer);

$out = [];
foreach ([
    'legacy_result'   => ['result'      => ['report_markdown' => '## from result']],
    'agent_spelling'  => ['result_json' => ['report_markdown' => '## from result_json']],
    'no_body'         => [],
] as $label => $extra) {
    $id = $repo->insert(array_merge([
        'ts' => gmdate('c'), 'type' => 'conductor_report', 'run_id' => 'r-' . $label,
        'actor_action_id' => 's-' . $label,
    ], $extra));
    $row = $conn->fetch('SELECT result_json FROM events WHERE id = ?', $id);
    $out[$label] = $row->result_json;
}

// THE READER ITSELF, against this real database — the predicate the Runner
// builds, transcribed. Stubbing it is how it shipped wrong twice.
$reader = static function (string $session) use ($repo): bool {
    $found = $repo->query(['type' => 'conductor_report', 'actor_action_id' => $session], 1)['items'] ?? [];
    $body = $found === [] ? null : ($found[0]['result_json'] ?? null);
    return is_string($body) && trim($body) !== '' && trim($body) !== '[]' && trim($body) !== '{}';
};
$out['reader'] = [
    'with_body'    => $reader('s-agent_spelling'),
    'without_body' => $reader('s-no_body'),
    'no_such_run'  => $reader('s-never-happened'),
];
echo json_encode($out);
"""


def _probe() -> dict:
    p = WING / "events-body-probe.php"
    p.write_text("<?php\n" + PROBE, encoding="utf-8")
    try:
        out = subprocess.run(
            ["php", p.name], cwd=WING, capture_output=True, text=True, timeout=90,
            env={"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
                 "HOME": str(Path.home()),
                 "NOS_INIT_DB": str(WING / "bin/init-db.php")},
        )
    finally:
        p.unlink(missing_ok=True)
    assert out.returncode == 0, out.stderr or out.stdout
    return json.loads(out.stdout.strip().splitlines()[-1])


@needs_report_vendor
def test_the_agent_spelling_is_stored() -> None:
    """`result_json` is what four agent prompts tell the model to send."""
    got = _probe()["agent_spelling"]
    assert got, "an agent's report body was dropped on insert — this is 461db38c"
    assert "from result_json" in got


@needs_report_vendor
def test_the_in_process_spelling_still_works() -> None:
    """AuditEmitter and Runner send `result`; the fix must not move the goalposts."""
    got = _probe()["legacy_result"]
    assert got and "from result" in got


@needs_report_vendor
def test_no_body_stores_null_rather_than_an_empty_object() -> None:
    """Absent and empty must stay tellable apart at the column."""
    assert _probe()["no_body"] in (None, "")


@needs_report_vendor
def test_the_deliverable_reader_answers_correctly_on_a_real_database() -> None:
    """The reader, RUN — not stubbed. query() returns ['items'=>…, 'total'=>n]:
    `!== []` was always true (461db38c), `$rows[0]` always null (245cf5e9)."""
    got = _probe()["reader"]
    assert got["with_body"] is True, (
        "a report that IS in the table reads as absent — this is 245cf5e9, "
        "where the agent revised twice against work it had already filed"
    )
    assert got["without_body"] is False, "an empty artifact counts as filed — 461db38c"
    assert got["no_such_run"] is False, "a session with no report at all reads as satisfied"


@needs_report_vendor
def test_the_runner_uses_that_shape() -> None:
    """And the transcription above matches the code it stands in for."""
    src = (APP / "AgentKit/Runner.php").read_text(encoding="utf-8")
    i = src.index("deliverableEvent === null")
    body = src[i:i + 1800]
    assert "['items']" in body, "the reader no longer unwraps query()'s envelope"
    for empty in ("'[]'", "'{}'"):
        assert empty in body, f"an artifact of {empty} counts as filed"


# ── questions ledger ─────────────────────────────────────────────────────────
# agent_questions has NO sweeper; only a late answer writes status='expired', so a count
# on that column reads zero forever. countExpired()'s WHERE is lifted from the PHP and
# executed on real SQLite with a row of every shape.

SCHEMA = WING / "db/schema-extensions.sql"
QUESTIONS_PRESENTER = PRESENTERS / "QuestionsPresenter.php"
QUESTIONS_TEMPLATE = APP / "Templates/Questions/default.latte"

NOW = "2026-08-28T12:00:00Z"
PAST = "2026-08-28T11:00:00Z"


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
    """The WHERE the shipped code issues, plus the params it binds (lifted, never restated)."""
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
    """Swept-only counting reports ONE where the truth is two, and zero on a quiet estate."""
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
    """listRecent() must apply the same deadline rule poll() does."""
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
    """/questions is read-only; answering stays on /inbox (resolve-once UPDATE, CSRF)."""
    src = QUESTIONS_PRESENTER.read_text(encoding="utf-8")
    actions = re.findall(r"public function (action\w+)", src)
    assert actions == [], f"QuestionsPresenter grew mutating actions: {actions}"
    tmpl = QUESTIONS_TEMPLATE.read_text(encoding="utf-8")
    assert "<form" not in tmpl, (
        "the questions template posts something — the answering path belongs to "
        "/inbox"
    )
    assert re.search(r"addRoute\('questions',\s*'Questions:default'\)",
                     ROUTER.read_text(encoding="utf-8")), (
        "no /questions route — Nette renders an unroutable page as a 404 the "
        "nav tab still links to"
    )


# ── empty identity ───────────────────────────────────────────────────────────
# Roadmap person-disappears-at-the-api (2026-10-06): eight browser decision paths wrote
# `?? 'operator'` into the ledger. Now every presenter goes through requireActor(), which
# refuses (401). The tier gate already refused first, so the behavioural half was green before.

#: The paths the measurement named; the derived list must hold them.
KNOWN = {("Admin", "halt"), ("Admin", "resume"), ("Coexistence", "cancel"), ("Migrations", "markRejected"),
         ("Upgrades", "queueUpgrade"), ("Upgrades", "planChoice"), ("Upgrades", "cancelPlanned"),
         ("Upgrades", "promoteToMigration"), ("Agents", "kill"), ("Inbox", "answer")}


def decision_actions() -> list[tuple[str, str]]:
    """Routed browser actions that change state (they call requirePostMethod)."""
    routed = set(re.findall(r"\$router->addRoute\('[^']+',\s*'(\w+):(\w+)'\)", ROUTER.read_text(encoding="utf-8")))
    out = set()
    for p, a in routed:
        src = _php_code((PRESENTERS / f"{p}Presenter.php").read_text(encoding="utf-8"))
        for chunk in re.split(r"(?=\n\s*(?:public|private|protected)\s+(?:static\s+)?function\s)", src):
            m = re.match(r"\s*public function action(\w+)\(", chunk)
            if m and m.group(1)[0].lower() + m.group(1)[1:] == a and "requirePostMethod()" in chunk:
                out.add((p, a))
    return sorted(out)


def test_the_derived_list_holds_the_measured_paths():
    got = set(decision_actions())
    assert KNOWN <= got, f"derivation lost: {sorted(KNOWN - got)}"


def test_no_presenter_reads_the_person_around_require_actor():
    """One reader of the person, so one place decides what an empty one means."""
    offenders = []
    for f in sorted(PRESENTERS.glob("*Presenter.php")):
        if f.name == "BasePresenter.php":
            continue
        code = _php_code(f.read_text(encoding="utf-8"))
        for needle in ("X-Authentik-Username", "getUser()->getId()"):
            if needle in code:
                offenders.append(f"{f.name}: {needle}")
    assert not offenders, (
        "browser presenter(s) read the forward-auth person directly; route it through "
        f"BasePresenter::requireActor(), which refuses instead of defaulting: {offenders}")


_IDENTITY_HARNESS = _AUTOLOAD_PRELUDE + r"""
putenv('NOS_WING_TRACING=0'); putenv('WING_EDGE_TOKEN='); putenv('BONE_URL=http://127.0.0.1:9');
function outcome(callable $f): array {
  try { $v = $f(); return ['code' => 'returned', 'value' => is_string($v) ? $v : null]; }
  catch (Nette\Application\BadRequestException $e) { return ['code' => $e->getHttpCode(), 'msg' => $e->getMessage()]; }
  catch (Error $e) {
    if (str_contains($e->getMessage(), 'must not be accessed before initialization')) return ['code' => 'reached'];
    return ['code' => 'error', 'msg' => $e->getMessage()];
  }
  catch (Throwable $e) { return ['code' => get_class($e), 'msg' => $e->getMessage()]; }
}
function presenter(string $name, array $headers): array {
  $cls = 'App\\Presenters\\' . $name . 'Presenter';
  $p = (new ReflectionClass($cls))->newInstanceWithoutConstructor();  // an unset dependency = no record
  $p->autoCanonicalize = false;
  $req = new Nette\Http\Request(new Nette\Http\UrlScript('http://wing/'), headers: $headers, method: 'POST');
  $p->injectPrimary($req, new Nette\Http\Response, user: new Nette\Security\User(new App\Security\ForwardAuthUserStorage($req)));
  return [$p, $cls];
}
$tier1 = ['x-authentik-username' => 'akadmin', 'x-authentik-groups' => 'nos-admins'];
$out = ['actions' => [], 'helper' => []];
foreach (json_decode($argv[2], true) as [$name, $action]) {
  $row = [];
  foreach (['none' => [], 'tier1' => $tier1] as $who => $h) {
    [$p, $cls] = presenter($name, $h);
    $params = ['action' => $action];
    foreach ((new ReflectionMethod($cls, 'action' . ucfirst($action)))->getParameters() as $param) {
      if (!$param->isOptional()) $params[$param->getName()] = 'x';
    }
    $row[$who] = outcome(fn() => $p->run(new Nette\Application\Request($name, 'POST', $params)));
  }
  $out['actions'][] = $row;
}
foreach (['none' => [], 'groups_only' => ['x-authentik-groups' => 'nos-admins'], 'tier1' => $tier1] as $who => $h) {
  [$p] = presenter('Admin', $h);
  $out['helper'][$who] = outcome(Closure::bind(fn() => $this->requireActor(), $p, $p));
}
echo json_encode($out);
"""


def _run() -> dict:
    r = subprocess.run(["php", "-d", "error_reporting=E_ALL", "-r", _IDENTITY_HARNESS, str(AUTOLOAD),
                        json.dumps(decision_actions())],
                       capture_output=True, text=True, timeout=120, check=False, cwd=WING)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(r.stdout)


@needs_php
@needs_vendor
def test_no_identity_no_record():
    got = _run()
    for (p, a), row in zip(decision_actions(), got["actions"]):
        assert row["none"]["code"] in (401, 403), f"{p}:{a} with no identity: {row['none']}"
        # Control: the harness can get past the gate, so the refusal above is the gate's.
        assert row["tier1"]["code"] not in (401, 403) or "CSRF" in row["tier1"].get("msg", ""), \
            f"{p}:{a} refused a Tier-1 identity: {row['tier1']}"


@needs_php
@needs_vendor
def test_require_actor_refuses_rather_than_invents():
    got = _run()
    assert got["helper"]["none"]["code"] == 401, got["helper"]
    assert got["helper"]["groups_only"]["code"] == 401, "groups without a username are not a person"
    assert got["helper"]["tier1"] == {"code": "returned", "value": "akadmin"}, got["helper"]


# ── approval queue ───────────────────────────────────────────────────────────
# A11 (2026-05-07) kept approvals as paired events; agents-inbox (2026-08-08) retired it after
# measuring the append-only race (approve + reject both "decided"). Contract: events = lineage
# (same event types), agent_questions = the one resolution row, decision emitted on the winning UPDATE.

RETIRED_PRESENTER = PRESENTERS / "ApprovalsPresenter.php"
RETIRED_TEMPLATE_DIR = APP / "Templates" / "Approvals"
EVENT_REPO = APP / "Model" / "EventRepository.php"
DB_DIR = WING / "db"


def _schema_sql() -> str:
    return "\n".join(p.read_text() for p in sorted(DB_DIR.glob("*.sql")))


def test_the_a11_surface_is_gone():
    """Presenter, template and verb routes are retired — not half-retired."""
    assert not RETIRED_PRESENTER.exists(), (
        "ApprovalsPresenter.php is back. Approvals are kind='approval' "
        "questions answered on /inbox; a second decision surface reintroduces "
        "the append-only race this file's docblock records."
    )
    assert not RETIRED_TEMPLATE_DIR.exists(), (
        "Templates/Approvals/ is back without its presenter — a template "
        "nothing renders, or a resurrected surface. Neither is intended."
    )
    router_code = _php_code(ROUTER.read_text())
    verb_routes = re.findall(r"addRoute\('approvals/[^']*'", router_code)
    assert not verb_routes, (
        f"RouterFactory still routes A11 verb forms: {verb_routes} — these "
        "targeted ApprovalsPresenter::actionApprove/actionReject, which no "
        "longer exist."
    )


def test_the_legacy_url_lands_on_the_successor():
    """/approvals redirects to /inbox rather than 404ing."""
    router_code = _php_code(ROUTER.read_text())
    assert re.search(r"addRoute\('approvals',\s*'Inbox:approvals'\)", router_code), (
        "the bare 'approvals' route no longer lands on Inbox:approvals — "
        "either restore the redirect route or update this gate alongside a "
        "deliberate decision to 404."
    )
    inbox = _php_code((PRESENTERS / "InboxPresenter.php").read_text())
    m = re.search(
        r"public function actionApprovals\(\)\s*:\s*void\s*\{(.*?)\n\t\}",
        inbox, re.DOTALL,
    )
    assert m and "redirectPermanent" in m.group(1), (
        "InboxPresenter::actionApprovals() does not permanently redirect to "
        "the inbox — the legacy URL must answer with the successor, not 404."
    )


def test_still_no_second_approval_store_in_schema():
    """The RESOLUTION lives in agent_questions and nowhere else."""
    sql = _schema_sql()
    for table in ("approval_requests", "approval_decisions", "agent_approvals"):
        assert not re.search(
            rf"create\s+table\s+(if\s+not\s+exists\s+)?[\"`']?{table}\b",
            sql, re.IGNORECASE,
        ), (
            f"A dedicated `{table}` table appeared in the Wing schema. The "
            f"resolution store is agent_questions (kind='approval'); a second "
            f"store reintroduces the drift the A11 gate was protecting against."
        )
    assert re.search(
        r"create\s+table\s+(if\s+not\s+exists\s+)?[\"`']?agent_questions\b",
        sql, re.IGNORECASE,
    ), (
        "agent_questions vanished from the schema — the resolution store is "
        "gone while this gate still certifies it."
    )


def test_the_approval_event_types_survive_and_have_one_writer():
    """A11's vocabulary survives; only AgentQuestionRepository writes the decision event."""
    repo_code = _php_code(REPOSITORY.read_text())
    assert "'agent_approval_request'" in repo_code, (
        "AgentQuestionRepository no longer emits agent_approval_request for "
        "kind='approval' asks — audit queries keyed on A11's types break."
    )
    assert "'agent_approval_decision'" in repo_code, (
        "AgentQuestionRepository no longer emits agent_approval_decision on "
        "the winning answer — the lineage loses the decision."
    )

    writers = []
    for php in APP.rglob("*.php"):
        if php == REPOSITORY or php == EVENT_REPO:
            continue
        code = _php_code(php.read_text(encoding="utf-8"))
        if "agent_approval_decision" in code:
            writers.append(str(php.relative_to(REPO)))
    assert not writers, (
        f"agent_approval_decision appears in code outside AgentQuestionRepository "
        f"/ EventRepository's registry: {writers}. The decision event must be "
        f"emitted ONLY on the winning conditional UPDATE — a second writer is "
        f"how approve+reject both got recorded under A11."
    )


def test_the_decision_event_rides_the_winning_update():
    """The emit sits inside the `$affected === 1` branch of answer() and answerAsOperator()."""
    code = _php_code(REPOSITORY.read_text())
    for method in ("public function answer(", "public function answerAsOperator("):
        start = code.find(method)
        assert start != -1, f"{method} not found in AgentQuestionRepository"
        # Body up to the next public method.
        nxt = code.find("public function", start + len(method))
        body = code[start : nxt if nxt != -1 else len(code)]
        cond = body.find("$affected === 1")
        emit = body.find("$this->emit(")
        assert cond != -1 and emit != -1 and emit > cond, (
            f"in {method} the decision emit does not follow the "
            f"affected-row check — a losing (or failed) answer could emit a "
            f"decision event, which is exactly the A11 defect."
        )


# ── question click ───────────────────────────────────────────────────────────
# agents-inbox review (2026-08-08): AskOperatorTool asked via the repository, which notified
# nobody; and no notification set click_url, so the phone had no way to act. The insert lives
# in ask(); the click is `<WING_PUBLIC_URL>/inbox` — a link, never a credential.

API_PRESENTER = PRESENTERS / "Api/InboxPresenter.php"
TOOL = APP / "AgentKit/Tools/AskOperatorTool.php"
PLIST = REPO / "roles/pazny.wing/templates/wing.plist.j2"
ENVFILE = REPO / "roles/pazny.wing/templates/wing.env.j2"


def ask_body() -> str:
    code = _php_code(REPOSITORY.read_text(encoding="utf-8"))
    start = code.find("public function ask(")
    end = code.find("public function answer(")
    assert start != -1 and end != -1 and start < end, (
        "AgentQuestionRepository::ask() body not locatable — the method moved; "
        "re-point this gate rather than letting it pass vacuously."
    )
    return code[start:end]


def test_the_ask_path_itself_notifies():
    """Both ask paths (HTTP and AskOperatorTool) must notify from ONE place."""
    assert "$this->notifications->insert(" in ask_body(), (
        "AgentQuestionRepository::ask() no longer inserts the notification. "
        "AskOperatorTool calls the repository directly — with the insert at a "
        "call site, a tool-asked question reaches no phone and no mailbox and "
        "decides itself at the deadline."
    )


def test_the_click_url_points_at_the_inbox_and_names_no_secret():
    body = ask_body()
    m = re.search(r"'click_url'\s*=>\s*([^\n]+)", body)
    assert m, (
        "the question notification no longer carries metadata.click_url — "
        "deliver_ntfy reads exactly that key for its Click header, and a "
        "notification without it is a dead end on a phone."
    )
    expr = m.group(1)
    assert "'/inbox'" in expr, (
        f"click_url no longer targets /inbox: {expr!r}. The link must land on "
        "a surface that authenticates the reader."
    )
    for forbidden in ("$token", "reply", "$uuid", "question"):
        assert forbidden not in expr, (
            f"click_url expression contains {forbidden!r}: {expr!r}. The URL "
            "lands in metadata_json, ntfy's cache and the phone's history — "
            "it must carry no credential and no per-question addressing."
        )
    assert "null" in expr, (
        f"click_url has no explicit empty-env branch: {expr!r}. With "
        "WING_PUBLIC_URL unset the value must be null (no Click header), "
        "never a fabricated URL."
    )


def test_the_public_url_is_provisioned_on_both_platforms():
    """WING_PUBLIC_URL must reach the daemon env on macOS (plist) AND Linux (wing.env)."""
    plist = PLIST.read_text(encoding="utf-8")
    assert re.search(
        r"<key>WING_PUBLIC_URL</key>\s*<string>https://\{\{ wing_domain \}\}</string>",
        plist,
    ), "wing.plist.j2 does not provision WING_PUBLIC_URL=https://{{ wing_domain }}"
    env = ENVFILE.read_text(encoding="utf-8")
    assert re.search(
        r"^WING_PUBLIC_URL=https://\{\{ wing_domain \}\}$", env, re.M
    ), "wing.env.j2 does not provision WING_PUBLIC_URL=https://{{ wing_domain }}"


def test_the_api_presenter_does_not_double_notify():
    """One insert, one place — a second at the HTTP call site notifies twice."""
    code = _php_code(API_PRESENTER.read_text(encoding="utf-8"))
    assert "$this->notifications->insert(" not in code, (
        "Api\\InboxPresenter inserts its own notification again — the insert "
        "lives in AgentQuestionRepository::ask() so BOTH ask paths notify "
        "exactly once."
    )


def test_the_tool_path_still_never_sees_the_token():
    """The tool must still discard the ask() result (holding the token) before any ToolResult."""
    code = _php_code(TOOL.read_text(encoding="utf-8"))
    assert "unset($made)" in code, (
        "AskOperatorTool no longer discards the ask() result holding the "
        "reply token before building a ToolResult."
    )
