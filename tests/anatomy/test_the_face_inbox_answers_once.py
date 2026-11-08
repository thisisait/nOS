"""The face Inbox app answers a question once, marks a notification read, and only for Tier 1.

Row wing-inc1-inbox-app (operator 2026-11-08). The face BFF speaks for a person with the
face-bff bearer and X-Nos-User-*; Wing decides the tier itself (requireOperator), the person
in the record is the edge identity (user:<uid>, via face), and a lost race is a 409 that names
the answer that won. Run over the REAL presenters and SQLite, as the medulla relay's gate is
(test_the_inbox_answers_once.py).
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
WING = REPO / "files/anatomy/wing"
AUTOLOAD = WING / "vendor/autoload.php"
FUTURE = "2099-01-01T00:00:00Z"

_HARNESS = r"""
$composer = require $argv[1];
$home = dirname(realpath($argv[1]), 2);
spl_autoload_register(function ($c) use ($composer, $home) {   // this tree's app/, even with vendor symlinked
  $own = getcwd() . '/app/' . str_replace('\\', '/', substr($c, 4)) . '.php';
  $f = realpath((string) $composer->findFile($c));
  if (str_starts_with($c, 'App\\') && is_file($own)) require $own;
  elseif ($f && str_starts_with($f, $home . '/app/')) require getcwd() . substr($f, strlen($home));
}, prepend: true);
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


@pytest.mark.skipif(not shutil.which("php"), reason="php runs Wing")
@pytest.mark.skipif(not AUTOLOAD.exists(), reason="wing vendor/autoload.php missing (composer install)")
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
    r = subprocess.run(["php", "-d", "error_reporting=E_ALL", "-r", _HARNESS, str(AUTOLOAD), str(tmp_path / "wing.db"), json.dumps(cases)],
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
