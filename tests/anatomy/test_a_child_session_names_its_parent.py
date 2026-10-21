"""A session started on behalf of another run is recorded as that run's child.

WHY (iris-agent-dendrogram, increment 2). Every run tree was one session deep:
POST /agents/<name>/sessions took no parent, so a run Iris or another agent
started could not be joined back to the run that asked for it.

THE SHAPE. One nullable column, agent_sessions.parent_ref: a bare Wing session
uuid (checked: exists and is the caller's), or `thalamus:<uuid>` for a parent
Wing cannot see (shape-checked only, recorded as claimed). One column, so the
link is one fact in one place; thread rows keep meaning threads of ONE session.

What runs: the REAL Api presenters over an in-memory SQLite built from the real
db/schema-extensions.sql, rows written by the real repository. The runner is a
recorder script, so the test sees the argv the parent reaches the runner with.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import time

from test_face_user_owns_its_sessions import (AUTOLOAD, WING, _agents, _bff, needs_php,
                                              needs_vendor)

A1 = "a1a1a1a1-0000-4000-8000-000000000001"   # alice's session
B1 = "b1b1b1b1-0000-4000-8000-000000000001"   # bob's session
A2 = "a2a2a2a2-0000-4000-8000-000000000002"   # alice's child of A1
X2 = "c2c2c2c2-0000-4000-8000-000000000002"   # someone else's child of A1
T1 = "d1d1d1d1-0000-4000-8000-000000000001"   # a thalamus run's child
THAL = "thalamus:e1e1e1e1-0000-4000-8000-000000000001"

_HARNESS = r"""
$composer = require $argv[1];
$home = dirname(realpath($argv[1]), 2);
spl_autoload_register(function ($c) use ($composer, $home) {
  $own = getcwd() . '/app/' . str_replace('\\', '/', substr($c, 4)) . '.php';
  $f = realpath((string) $composer->findFile($c));
  if (str_starts_with($c, 'App\\') && is_file($own)) require $own;
  elseif ($f && str_starts_with($f, $home . '/app/')) require getcwd() . substr($f, strlen($home));
}, prepend: true);
class_exists(App\AgentKit\Agent::class);
putenv('WING_PHP_BIN=' . $argv[4]);
$pdo = new Nette\Database\Connection('sqlite::memory:');
$pdo->getPdo()->exec(file_get_contents('db/schema-extensions.sql'));
$pdo->query("CREATE TABLE api_tokens (id INTEGER PRIMARY KEY, token TEXT, name TEXT, active INT DEFAULT 1, scopes TEXT, last_used_at TEXT)");
foreach (['bff-secret' => 'face-bff', 'ops-secret' => 'ansible-provisioned'] as $t => $n) {
  $pdo->query('INSERT INTO api_tokens', ['token' => hash('sha256', $t), 'name' => $n, 'scopes' => 'wing.write']);
}
$cache = new Nette\Caching\Storages\DevNullStorage;
$structure = new Nette\Database\Structure($pdo, $cache);
$db = new Nette\Database\Explorer($pdo, $structure, new Nette\Database\Conventions\DiscoveredConventions($structure), $cache);
$loader = new App\AgentKit\AgentLoader($argv[2]);
$sessions = new App\Model\AgentSessionRepository($db);
foreach (json_decode($argv[5], true) as [$uuid, $agent, $actor, $parent]) {
  $sessions->startSession(['uuid' => $uuid, 'agent_name' => $agent, 'agent_version' => 1, 'trigger' => 'operator',
    'actor_id' => $actor, 'trace_id' => str_repeat('0', 32), 'model_uri' => 'test', 'parent_ref' => $parent]);
}
$out = [];
foreach (json_decode($argv[3], true) as $c) {
  $p = $c['presenter'] === 'Agents'
    ? new App\Presenters\Api\AgentsPresenter($loader, $sessions, new App\AgentKit\OperatorTrigger($loader))
    : new App\Presenters\Api\AgentSessionsPresenter($sessions);
  $p->tokenRepo = new App\Model\TokenRepository($db);
  $p->autoCanonicalize = false;
  $headers = array_filter(['authorization' => 'Bearer ' . $c['token'],
    'x-nos-user-uid' => $c['uid'] ?? null, 'x-nos-user-groups' => $c['groups'] ?? null]);
  $body = isset($c['body']) ? json_encode($c['body']) : '';
  $req = new Nette\Http\Request(new Nette\Http\UrlScript('http://wing/api'), headers: $headers,
    method: $c['method'], rawBodyCallback: fn() => $body);
  $res = new Nette\Http\Response;
  $p->injectPrimary($req, $res);
  $r = $p->run(new Nette\Application\Request('Api:' . $c['presenter'], $c['method'], $c['params']));
  $payload = $r instanceof Nette\Application\Responses\JsonResponse ? $r->getPayload() : null;
  $out[] = ['code' => $res->getCode(), 'body' => $payload];
}
echo json_encode($out);
"""

_SEED = [
    [A1, "helper", "user:alice", None],
    [B1, "helper", "user:bob", None],
    [A2, "ops-triage", "user:alice", A1],
    [X2, "ops-triage", "ansible-provisioned", A1],
    [T1, "helper", "user:alice", THAL],
]


def _run(tmp_path: pathlib.Path, cases: list[dict]) -> tuple[list[dict], pathlib.Path]:
    log = tmp_path / "argv.log"
    recorder = tmp_path / "runner.sh"
    recorder.write_text(f"#!/bin/sh\nprintf '%s\\n' \"$@\" '--' >> '{log}'\n", encoding="utf-8")
    recorder.chmod(0o755)
    r = subprocess.run(["php", "-d", "error_reporting=E_ALL", "-r", _HARNESS, str(AUTOLOAD),
                        str(_agents(tmp_path)), json.dumps(cases), str(recorder), json.dumps(_SEED)],
                       capture_output=True, text=True, timeout=60, check=False, cwd=WING)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(r.stdout), log


def _open(parent, **who) -> dict:
    return {"presenter": "Agents", "method": "POST", "params": {"action": "sessions", "name": "helper"},
            "body": {"prompt": "hi", "parent": parent}, **who}


def _get(uuid: str, **who) -> dict:
    return {"presenter": "AgentSessions", "method": "GET", "params": {"action": "default", "uuid": uuid}, **who}


def _runner_argv(log: pathlib.Path, spawns: int) -> list[list[str]]:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        calls = log.read_text(encoding="utf-8").split("--\n")[:-1] if log.exists() else []
        if len(calls) >= spawns:
            return [c.splitlines() for c in calls]
        time.sleep(0.05)
    raise AssertionError(f"the runner was spawned fewer than {spawns} times")


@needs_php
@needs_vendor
def test_a_parent_is_checked_before_anything_spawns(tmp_path):
    own, thal, theirs, absent, malformed, other_origin, not_str = _run(tmp_path, [
        _open(A1, **_bff()),
        _open(THAL, **_bff()),
        _open(B1, **_bff()),                       # bob's session: answers like an absent one
        _open("ffffffff-0000-4000-8000-00000000000f", **_bff()),
        _open("not-a-uuid", **_bff()),
        _open("keap:" + A1, **_bff()),             # only the thalamus is a known outside parent
        _open(["x"], **_bff()),
    ])[0]
    assert own["code"] == 202 and thal["code"] == 202, (own, thal)
    assert theirs["code"] == absent["code"] == 404 and theirs["body"] == absent["body"]
    assert malformed["code"] == other_origin["code"] == not_str["code"] == 400


@needs_php
@needs_vendor
def test_the_parent_reaches_the_runner(tmp_path):
    (opened,), log = _run(tmp_path, [_open(A1, **_bff())])
    assert opened["code"] == 202
    (argv,) = _runner_argv(log, 1)
    assert f"--parent={A1}" in argv, argv


@needs_php
@needs_vendor
def test_a_session_lists_its_children_and_names_its_parent(tmp_path):
    alice_root, admin_root, alice_child, alice_thal = _run(tmp_path, [
        _get(A1, **_bff()),
        _get(A1, **_bff(groups="nos-admins")),
        _get(A2, **_bff()),
        _get(T1, **_bff()),
    ])[0]
    kids = alice_root["body"]["children"]
    assert [k["uuid"] for k in kids] == [A2], "another actor's child of my session is not listed to me"
    assert set(kids[0]) == {"uuid", "agent_name", "status", "started_at", "ended_at", "stop_reason",
                            "outcome_result"}, "a child is a summary row, not the whole session"
    assert sorted(k["uuid"] for k in admin_root["body"]["children"]) == sorted([A2, X2])
    assert alice_root["body"]["session"]["parent_ref"] is None
    assert alice_child["body"]["session"]["parent_ref"] == A1
    assert alice_child["body"]["children"] == []
    assert alice_thal["body"]["session"]["parent_ref"] == THAL


def test_an_existing_wing_db_gains_the_column():
    """CREATE TABLE IF NOT EXISTS is a no-op on a live wing.db; only the sweep adds it."""
    from test_a_successor_retires_its_predecessors import _swept_columns
    assert "parent_ref" in _swept_columns().get("agent_sessions", set())
