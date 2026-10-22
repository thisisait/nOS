"""A running agent session can be stopped by whoever may see it, and the Runner honours the stop.

WHY (roadmap iris-subagent-stop). Iris could start a Wing agent (start_agent) and
draw its run (read_run), but nothing could end it early: the Runner's only bounds
were the call cap, the wall clock and the token ceiling, and Wing's emergency halt
pauses every Pulse job, operator-only. POST /api/v1/agent-sessions/<uuid>/cancel
marks the row `cancelled`; the Runner reads the row before every model call and
ends there. Cooperative: the call in flight finishes, no process is signalled.

What runs: (1) the REAL Api presenter over an in-memory SQLite built from the real
db/schema-extensions.sql (the harness of test_a_child_session_names_its_parent.py
plus a thalamus token row); (2) the real Runner's tool-use loop over a stub client
and a stub session store, which flips the row mid-run.
"""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

import pytest

from test_a_child_session_names_its_parent import _HARNESS
from test_face_user_owns_its_sessions import AUTOLOAD, WING, _agents, needs_php, needs_vendor

THAL = "thalamus:e1e1e1e1-0000-4000-8000-000000000001"     # the Iris session that started T1
OTHER = "thalamus:e2e2e2e2-0000-4000-8000-000000000002"    # another Iris session
T1 = "d1d1d1d1-0000-4000-8000-000000000001"   # alice's run, started by Iris (THAL)
T2 = "d2d2d2d2-0000-4000-8000-000000000002"   # alice's run, started by Iris (THAL)
B2 = "b2b2b2b2-0000-4000-8000-000000000002"   # bob's run, started by Iris (THAL)
A1 = "a1a1a1a1-0000-4000-8000-000000000001"   # alice's run, started from the face, not by Iris
ABSENT = "ffffffff-0000-4000-8000-00000000000f"

_TOKENS = "foreach (['bff-secret' => 'face-bff', 'ops-secret' => 'ansible-provisioned'] as $t => $n) {"
_SEED = [
    [T1, "helper", "user:alice", THAL],
    [T2, "helper", "user:alice", THAL],
    [B2, "helper", "user:bob", THAL],
    [A1, "helper", "user:alice", None],
]


def _harness() -> str:
    assert _HARNESS.count(_TOKENS) == 1, "the borrowed harness moved"
    return _HARNESS.replace(_TOKENS, "$pdo->query('INSERT INTO api_tokens', ['token' => hash('sha256', 'thal'), "
                                     "'name' => 'thalamus', 'scopes' => 'wing.write']);\n" + _TOKENS)


def _run(tmp_path: pathlib.Path, cases: list[dict]) -> list[dict]:
    r = subprocess.run(["php", "-d", "error_reporting=E_ALL", "-r", _harness(), str(AUTOLOAD),
                        str(_agents(tmp_path)), json.dumps(cases), "/usr/bin/true", json.dumps(_SEED)],
                       capture_output=True, text=True, timeout=60, check=False, cwd=WING)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(r.stdout)


def _thal(uid="alice", groups="nos-users") -> dict:
    return {"token": "thal", "uid": uid, "groups": groups}


def _cancel(uuid: str, parent: str | None = THAL, **who) -> dict:
    return {"presenter": "AgentSessions", "method": "POST", "params": {"action": "cancel", "uuid": uuid},
            "body": {} if parent is None else {"parent": parent}, **who}


def _get(uuid: str) -> dict:
    return {"presenter": "AgentSessions", "method": "GET", "params": {"action": "default", "uuid": uuid},
            "token": "bff-secret", "uid": "alice", "groups": "nos-users"}


@needs_php
@needs_vendor
def test_the_thalamus_stops_a_run_it_started_and_the_row_says_who(tmp_path):
    stopped, read, again = _run(tmp_path, [_cancel(T1, **_thal()), _get(T1), _cancel(T1, **_thal())])
    assert stopped["code"] == 202, stopped
    row = read["body"]["session"]
    assert (row["status"], row["stop_reason"]) == ("cancelled", "cancelled by user:alice"), row
    assert again["code"] == 409, "a session that is not running is not stopped twice"


@needs_php
@needs_vendor
def test_what_the_thalamus_did_not_start_answers_like_absent(tmp_path):
    """Another person's run, a run of the person's not started by Iris, a run another Iris
    session started, and no run at all answer the same 404: absent and not-yours alike."""
    theirs, faced, other_iris, absent, unnamed = _run(tmp_path, [
        _cancel(B2, **_thal()),
        _cancel(A1, **_thal()),
        _cancel(T2, OTHER, **_thal()),
        _cancel(ABSENT, **_thal()),
        _cancel(T2, None, **_thal()),
    ])
    for got in (theirs, faced, other_iris, unnamed):
        assert (got["code"], got["body"]) == (absent["code"], absent["body"]), got
    assert absent["code"] == 404


@needs_php
@needs_vendor
def test_an_agent_token_stops_nothing(tmp_path):
    """No person behind the bearer: stopping someone's run is an operator decision."""
    ops, = _run(tmp_path, [_cancel(T2, token="ops-secret")])
    assert ops["code"] == 403, ops


@needs_php
@needs_vendor
def test_the_face_bff_stops_nothing(tmp_path):
    """The row widened the thalamus alone: the face-bff bearer, Tier 1 or not, reaches no cancel,
    and the run it named is still running afterwards."""
    user, admin, read = _run(tmp_path, [
        _cancel(A1, None, token="bff-secret", uid="alice", groups="nos-users"),
        _cancel(A1, None, token="bff-secret", uid="alice", groups="nos-admins"),
        _get(A1),
    ])
    assert (user["code"], admin["code"]) == (403, 403), (user, admin)
    assert read["body"]["session"]["status"] == "running", read


_LOOP = r"""<?php
namespace App\Model { final class EventRepository { public function insert(array $p): int { return 1; } }
  final class AgentSessionRepository { public array $rows = [];
    public function findByUuid(string $u): ?array { return $this->rows[$u] ?? null; } } }
namespace {
use App\AgentKit\LLMClient\{LLMClientInterface, LLMResponse};
spl_autoload_register(function ($c) { $f = WING . '/app/' . str_replace('\\', '/', substr($c, 4)) . '.php';
    if (str_starts_with($c, 'App\\') && is_file($f)) require $f; });
$store = new App\Model\AgentSessionRepository();
$store->rows['s'] = ['status' => 'running', 'stop_reason' => null];
final class Stub implements LLMClientInterface {
    public int $calls = 0;
    public function __construct(private App\Model\AgentSessionRepository $store, private int $stopAt) {}
    public function identifier(): string { return 'stub'; }
    public function send(string $s, array $m, array $t = [], int $x = 4096): LLMResponse {
        if (++$this->calls === $this->stopAt) {
            $this->store->rows['s'] = ['status' => 'cancelled', 'stop_reason' => 'cancelled by user:alice'];
        }
        return new LLMResponse('tool_use', [['type' => 'tool_use', 'id' => 't' . $this->calls, 'name' => 'look', 'input' => []]], 1, 1);
    }
}
$agent = new App\AgentKit\Agent(name: 'x', version: 1, description: '', modelPrimaryUri: 'stub',
    modelFallbackUri: null, modelGraderUri: null, systemPrompt: 'SYS', tools: [], rubric: null,
    maxIterations: 1, capabilityScopes: [], piiClassification: 'none', requiredCredentials: [],
    subscriptions: [], metadata: [], sourceDir: '');
$llm = new Stub($store, 2);
$r = (new ReflectionClass(App\AgentKit\Runner::class))->newInstanceWithoutConstructor();
(function () use ($store) {
    $this->audit = new App\AgentKit\Telemetry\AuditEmitter(new App\Model\EventRepository());
    $this->sessions = $store;
    $this->sessionUuid = 's';
    $this->sessionDeadline = microtime(true) + 600;
    $this->fallbackContext = ['session_uuid' => 's', 'primary' => 'stub'];
})->call($r);
$out = ['calls' => null, 'threw' => null];
try {
    (function () use ($agent, $llm) { $spans = [];
        $this->runToolUseLoop($agent, $llm, [], [App\AgentKit\LLMClient\Message::userText('go')], 's', 'th', str_repeat('0', 32), str_repeat('0', 16), 'x', $spans);
    })->call($r);
} catch (Throwable $e) { $out['threw'] = get_class($e); $out['why'] = $e->getMessage(); }
$out['calls'] = $llm->calls;
$closing = fn () => method_exists($this, 'closing') ? $this->closing('s', 'idle', 'end_turn') : null;
$out['closing'] = $closing->call($r);
$store->rows['s'] = ['status' => 'running', 'stop_reason' => null];
$out['open'] = $closing->call($r);
echo json_encode($out);
}
"""


@pytest.mark.skipif(shutil.which("php") is None, reason="php not installed on this runner")
def test_the_loop_ends_at_the_next_call_after_the_stop(tmp_path):
    """The row turns cancelled during call 2: call 3 is never made, and the session
    closes with the stop's own status and reason instead of the loop's."""
    script = tmp_path / "loop.php"
    script.write_text(_LOOP.replace("WING", repr(str(WING))), encoding="utf-8")
    r = subprocess.run(["php", "-d", "display_errors=stderr", str(script)], capture_output=True, text=True, timeout=60, check=False)
    assert r.returncode == 0, r.stdout + r.stderr
    got = json.loads(r.stdout)
    assert got["calls"] == 2, f"the loop went on after the stop: {got}"
    assert got["threw"] == "App\\AgentKit\\SessionCancelled", got
    assert got["closing"] == ["cancelled", "cancelled by user:alice"], got
    assert got["open"] == ["idle", "end_turn"], "a session nobody stopped closes as the loop says"
