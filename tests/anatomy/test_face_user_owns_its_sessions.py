"""An end user's identity reaches agent_sessions, and stops at their own rows.

WHY (face-i0-identity, 2026-10-06). The face BFF opened Wing sessions with the
estate's operator bearer, so every session a user started was stamped with the
token's name (`ansible-provisioned`) and every user could list every session.
files/anatomy/contracts/face-wing.yml §2-3 is the fix: only the `face-bff`
bearer may speak for a user; Wing stamps actor_id = user:<uid> and narrows reads.

What runs: (1) EndUser, pure PHP; (2) the REAL Api presenters, executed through
Nette's Presenter::run over an in-memory SQLite wing.db (needs the wing vendor
tree). No runner starts: WING_PHP_BIN is /usr/bin/true, so a spawn execs `true`.
"""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
WING = REPO / "files/anatomy/wing"
AUTOLOAD = WING / "vendor/autoload.php"

needs_php = pytest.mark.skipif(not shutil.which("php"), reason="php runs Wing")
needs_vendor = pytest.mark.skipif(not AUTOLOAD.exists(), reason="wing vendor/autoload.php missing (composer install)")

_PURE = r"""
require $argv[1]; require $argv[2];
use App\Security\EndUser;
$out = [];
foreach (json_decode($argv[3], true) as [$tok, $uid, $groups]) {
  try { $u = EndUser::fromRequest($tok, $uid, $groups);
        $out[] = $u === null ? null : [$u->actorId(), $u->scope()]; }
  catch (DomainException $e) { $out[] = $e->getCode(); }
}
echo json_encode($out);
"""

_PRESENTERS = r"""
$composer = require $argv[1];
// App\ from THIS tree, even when vendor/ is a symlink into another checkout.
$home = dirname(realpath($argv[1]), 2);
spl_autoload_register(function ($c) use ($composer, $home) {
  $own = getcwd() . '/app/' . str_replace('\\', '/', substr($c, 4)) . '.php';
  $f = realpath((string) $composer->findFile($c));
  if (str_starts_with($c, 'App\\') && is_file($own)) require $own;
  elseif ($f && str_starts_with($f, $home . '/app/')) require getcwd() . substr($f, strlen($home));
}, prepend: true);
class_exists(App\AgentKit\Agent::class);  // Agent.php also declares VaultRequirement & co.
putenv('WING_PHP_BIN=/usr/bin/true');
$agents = $argv[2];
$pdo = new Nette\Database\Connection('sqlite::memory:');
$pdo->query("CREATE TABLE api_tokens (id INTEGER PRIMARY KEY, token TEXT, name TEXT, active INT DEFAULT 1, scopes TEXT, last_used_at TEXT)");
$pdo->query("CREATE TABLE agent_sessions (id INTEGER PRIMARY KEY, uuid TEXT, agent_name TEXT, actor_id TEXT, status TEXT)");
$pdo->query("CREATE TABLE agent_threads (id INTEGER PRIMARY KEY, session_uuid TEXT)");
$pdo->query("CREATE TABLE agent_iterations (id INTEGER PRIMARY KEY, session_uuid TEXT, iteration INT)");
foreach (['bff-secret' => 'face-bff', 'ops-secret' => 'ansible-provisioned'] as $t => $n) {
  $pdo->query('INSERT INTO api_tokens', ['token' => hash('sha256', $t), 'name' => $n, 'scopes' => 'wing.write']);
}
foreach ([['a1', 'user:alice'], ['b1', 'user:bob'], ['c1', 'conductor']] as [$u, $a]) {
  $pdo->query('INSERT INTO agent_sessions', ['uuid' => $u, 'agent_name' => 'helper', 'actor_id' => $a, 'status' => 'idle']);
}
$cache = new Nette\Caching\Storages\DevNullStorage;
$structure = new Nette\Database\Structure($pdo, $cache);
$db = new Nette\Database\Explorer($pdo, $structure, new Nette\Database\Conventions\DiscoveredConventions($structure), $cache);
$loader = new App\AgentKit\AgentLoader($agents);
$sessions = new App\Model\AgentSessionRepository($db);

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


def _php(script: str, *args: str) -> list:
    r = subprocess.run(["php", "-d", "error_reporting=E_ALL", "-r", script, *args],
                       capture_output=True, text=True, timeout=60, check=False, cwd=WING)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(r.stdout)


@needs_php
def test_only_the_bff_bearer_speaks_for_a_user():
    cases = [
        ["ansible-provisioned", "alice", "nos-users"],   # headers on another token: ignored
        [None, "alice", "nos-users"],
        ["face-bff", "alice", "nos-users"],
        ["face-bff", "alice", "nos-users,nos-admins"],   # Tier 1 sees all
        ["face-bff", "Alice", ""],                       # not canonical
        ["face-bff", "", ""],
        ["face-bff", None, None],
        ["face-bff", "user:alice", ""],
    ]
    got = _php(_PURE, str(WING / "app/Security/CanonicalUid.php"),
               str(WING / "app/Security/EndUser.php"), json.dumps(cases))
    assert got == [None, None, ["user:alice", "user:alice"], ["user:alice", None], 401, 401, 401, 401]


def _agents(tmp_path: pathlib.Path) -> pathlib.Path:
    """ops-triage twice: as committed (not open to users) and opened."""
    root = tmp_path / "agents"
    shutil.copytree(REPO / "files/anatomy/agents/ops-triage", root / "ops-triage")
    shutil.copytree(REPO / "files/anatomy/agents/ops-triage", root / "helper")
    yml = root / "helper/agent.yml"
    text = yml.read_text(encoding="utf-8").replace("name: ops-triage", "name: helper", 1)
    yml.write_text(text.replace("metadata:\n", "metadata:\n  end_user: true\n", 1), encoding="utf-8")
    return root


def _run(tmp_path, cases: list[dict]) -> list[dict]:
    return _php(_PRESENTERS, str(AUTOLOAD), str(_agents(tmp_path)), json.dumps(cases))


def _bff(uid="alice", groups="nos-users", **kw) -> dict:
    return {"token": "bff-secret", "uid": uid, "groups": groups, **kw}


def _list(**who) -> dict:
    return {"presenter": "Agents", "method": "GET", "params": {"action": "sessions", "name": "helper"}, **who}


def _actors(res: dict) -> list[str]:
    return sorted(r["actor_id"] for r in res["body"]["data"])


@needs_php
@needs_vendor
def test_reads_are_narrowed_to_the_callers_own_sessions(tmp_path):
    alice, admin, ops, forged = _run(tmp_path, [
        _list(**_bff()),
        _list(**_bff(groups="nos-admins")),
        _list(token="ops-secret"),
        _list(token="ops-secret", uid="alice", groups="nos-users"),
    ])
    assert _actors(alice) == ["user:alice"]
    assert _actors(admin) == _actors(ops) == _actors(forged) == ["conductor", "user:alice", "user:bob"]


@needs_php
@needs_vendor
def test_someone_elses_session_answers_like_an_absent_one(tmp_path):
    def one(uuid, **who):
        return {"presenter": "AgentSessions", "method": "GET", "params": {"action": "default", "uuid": uuid}, **who}
    mine, theirs, missing, admin = _run(tmp_path, [
        one("a1", **_bff()), one("b1", **_bff()), one("zz", **_bff()), one("b1", **_bff(groups="nos-admins"))])
    assert mine["code"] == 200 and mine["body"]["session"]["actor_id"] == "user:alice"
    assert theirs["code"] == missing["code"] == 404
    assert theirs["body"] == missing["body"]
    assert admin["code"] == 200


@needs_php
@needs_vendor
def test_a_session_opened_through_the_bff_is_the_users(tmp_path):
    def open_(agent, body, **who):
        return {"presenter": "Agents", "method": "POST", "params": {"action": "sessions", "name": agent},
                "body": body, **who}
    opened, ops, closed, admin, vault, spoof = _run(tmp_path, [
        open_("helper", {"prompt": "hi"}, **_bff()),
        open_("helper", {"prompt": "hi"}, token="ops-secret", uid="alice", groups="nos-users"),
        open_("ops-triage", {}, **_bff()),
        open_("ops-triage", {}, **_bff(groups="nos-admins")),
        open_("helper", {"vault": "estate"}, **_bff()),
        open_("helper", {"actor_id": "conductor"}, **_bff()),
    ])
    assert opened["code"] == 202 and opened["body"]["actor_id"] == "user:alice"
    assert ops["body"]["actor_id"] == "ansible-provisioned", "X-Nos-User-* on another bearer must be ignored"
    assert closed["code"] == 403, "below Tier 1 a user opens only agents with metadata.end_user: true"
    assert admin["code"] == 202 and admin["body"]["actor_id"] == "user:alice"
    assert vault["code"] == 400 and spoof["code"] == 400


@needs_php
@needs_vendor
def test_the_bff_bearer_reaches_nothing_else(tmp_path):
    catalog, no_uid = _run(tmp_path, [
        {"presenter": "Agents", "method": "GET", "params": {"action": "default"}, **_bff()},
        _list(token="bff-secret"),
    ])
    assert catalog["code"] == 403
    assert no_uid["code"] == 401
