"""The emergency halt has a break-glass that needs neither face nor Traefik.

WHY (roadmap `halt-has-no-break-glass`, measured 2026-10-07). Halt/resume
existed only as the /admin Latte page: forward-auth through Traefik, so with
the edge down the operator had no way to stop every Pulse job. Now:

  * Wing API POST /api/v1/admin/{halt,resume} are operator verbs
    (Api\\AdminPresenter::$operatorActions) and record the actor;
  * `nos halt` / `nos resume` reach them over loopback :9000 with the
    wing-halt bearer (scope wing.halt), held only in ~/.nos/secrets.yml.

wing.halt carries those two verbs and no other operator decision; no agent
token carries it. The CLI is run against a stubbed Wing in a temp HOME; the
API runs the REAL presenters over a scratch wing.db (bin/init-db.php).
"""
from __future__ import annotations

import http.server
import json
import pathlib
import re
import shutil
import subprocess
import threading

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
NOS = REPO / "tools/nos"
WING = REPO / "files/anatomy/wing"
AUTOLOAD = WING / "vendor/autoload.php"
POST_YML = REPO / "roles/pazny.wing/tasks/post.yml"

needs_php = pytest.mark.skipif(not shutil.which("php"), reason="php runs Wing")
needs_vendor = pytest.mark.skipif(not AUTOLOAD.exists(), reason="wing vendor/autoload.php missing (composer install)")


# ── the CLI, against a stubbed Wing ─────────────────────────────────────────

class _Wing(http.server.BaseHTTPRequestHandler):
    seen: list = []
    code = 200

    def _answer(self):
        type(self).seen.append((self.command, self.path, self.headers.get("Authorization")))
        body = json.dumps({"halt_active": self.path.endswith("/halt")}).encode()
        self.send_response(type(self).code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = do_POST = _answer

    def log_message(self, *_):
        pass


@pytest.fixture()
def wing():
    _Wing.seen, _Wing.code = [], 200
    srv = http.server.HTTPServer(("127.0.0.1", 0), _Wing)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()


def _nos(tmp_path, srv, *args, token="f" * 64):
    (tmp_path / ".nos").mkdir(exist_ok=True)
    if token is not None:
        (tmp_path / ".nos/secrets.yml").write_text(f'wing_api_token: "agent-reachable"\nwing_halt_token: "{token}"\n')
    env = {"HOME": str(tmp_path), "PATH": "/usr/bin:/bin:/opt/homebrew/bin",
           "NOS_WING_URL": f"http://127.0.0.1:{srv.server_port}"}
    return subprocess.run(["bash", str(NOS), *args], env=env, capture_output=True, text=True, timeout=30)


def test_nos_halt_and_resume_reach_the_api_with_the_halt_bearer(tmp_path, wing):
    for args, want in ((["halt"], ("POST", "/api/v1/admin/halt")),
                       (["resume"], ("POST", "/api/v1/admin/resume")),
                       (["halt", "--status"], ("GET", "/api/v1/admin/state"))):
        r = _nos(tmp_path, wing, *args)
        assert r.returncode == 0, r.stdout + r.stderr
        assert _Wing.seen[-1] == (*want, "Bearer " + "f" * 64), _Wing.seen
    assert not any("agent-reachable" in (a or "") for *_, a in _Wing.seen), "the CLI sent the ansible-provisioned token"


def test_no_halt_token_sends_nothing(tmp_path, wing):
    r = _nos(tmp_path, wing, "halt", token=None)
    assert r.returncode == 69 and "wing_halt_token" in r.stderr, r.stdout + r.stderr
    r = _nos(tmp_path, wing, "halt", token="placeholder-regenerated-on-first-run")
    assert r.returncode == 69, r.stdout + r.stderr
    assert _Wing.seen == []


def test_a_refusal_is_not_success(tmp_path, wing):
    _Wing.code = 403
    r = _nos(tmp_path, wing, "halt")
    assert r.returncode == 1 and "HTTP 403" in r.stderr, r.stdout + r.stderr


def test_wing_down_is_unknown_not_ok(tmp_path, wing):
    port = wing.server_port
    wing.shutdown(); wing.server_close()
    env = {"HOME": str(tmp_path), "PATH": "/usr/bin:/bin", "WING_HALT_TOKEN": "f" * 64,
           "NOS_WING_URL": f"http://127.0.0.1:{port}"}
    r = subprocess.run(["bash", str(NOS), "halt"], env=env, capture_output=True, text=True, timeout=30)
    assert r.returncode == 69 and "UNKNOWN" in r.stderr, r.stdout + r.stderr


# ── who holds wing.halt ─────────────────────────────────────────────────────

def test_only_the_wing_halt_row_is_minted_with_the_halt_scope():
    src = POST_YML.read_text(encoding="utf-8")
    tasks = src.split("\n- name:")
    holders = [re.search(r"--name=([\w-]+)", t).group(1) for t in tasks if re.search(r"--scopes=[^\n]*wing\.halt", t)]
    assert holders == ["wing-halt"], holders
    block = next(t for t in tasks if "--name=wing-halt" in t)
    assert "wing.operator" not in block and "--token={{ wing_halt_token }}" in block, block
    for f in [*REPO.glob("roles/*/templates/*.j2"), *REPO.glob("files/anatomy/plugins/*/plugin.yml")]:
        assert "wing_halt_token" not in f.read_text(encoding="utf-8"), f"{f.relative_to(REPO)} renders the halt bearer"


@needs_php
def test_provision_token_reserves_the_halt_scope(tmp_path):
    subprocess.run(["php", str(WING / "bin/init-db.php"), f"--data-dir={tmp_path}"], capture_output=True, check=True, timeout=60)

    def mint(name: str) -> int:
        return subprocess.run(["php", str(WING / "bin/provision-token.php"), f"--db={tmp_path / 'wing.db'}",
                               "--token=t-" + name, f"--name={name}", "--scopes=wing.halt,wing.write"],
                              capture_output=True, timeout=60).returncode
    assert mint("ansible-provisioned") == 1 and mint("face-bff") == 1 and mint("librarian") == 1
    assert mint("wing-halt") == 0


# ── the API verbs, run ──────────────────────────────────────────────────────

_HARNESS = r"""
$composer = require $argv[1];
$home = dirname(realpath($argv[1]), 2);
spl_autoload_register(function ($c) use ($composer, $home) {   // this tree's app/, even with vendor symlinked
  $own = getcwd() . '/app/' . str_replace('\\', '/', substr($c, 4)) . '.php';
  $f = realpath((string) $composer->findFile($c));
  if (str_starts_with($c, 'App\\') && is_file($own)) require $own;
  elseif ($f && str_starts_with($f, $home . '/app/')) require getcwd() . substr($f, strlen($home));
}, prepend: true);
putenv('BONE_URL=http://127.0.0.1:9');
$pdo = new Nette\Database\Connection('sqlite:' . $argv[2]);
foreach (['agent' => ['librarian', 'wing.read,wing.write'], 'ansible' => ['ansible-provisioned', 'wing.write,pulse.write'],
          'halt' => ['wing-halt', 'wing.halt,wing.write'], 'bff' => ['face-bff', 'wing.operator,wing.write']] as $t => [$n, $s]) {
  $pdo->query('INSERT INTO api_tokens', ['token' => hash('sha256', $t), 'name' => $n, 'scopes' => $s, 'active' => 1]);
}
$cache = new Nette\Caching\Storages\DevNullStorage;
$structure = new Nette\Database\Structure($pdo, $cache);
$db = new Nette\Database\Explorer($pdo, $structure, new Nette\Database\Conventions\DiscoveredConventions($structure), $cache);
$pulse = new App\Model\PulseRepository($db);
$events = new App\Model\EventRepository($db);
$pulse->upsertJob(['plugin_name' => 'p', 'job_name' => 'j', 'command' => '/usr/bin/true', 'schedule' => '*/5 * * * *']);
$out = [];
foreach (json_decode($argv[3], true) as $c) {
  $cls = 'App\\Presenters\\Api\\' . $c['presenter'] . 'Presenter';
  $p = $c['presenter'] === 'Admin' ? new $cls($pulse, $events) : (new ReflectionClass($cls))->newInstanceWithoutConstructor();
  $p->tokenRepo = new App\Model\TokenRepository($db);
  $p->autoCanonicalize = false;
  $headers = array_filter(['authorization' => 'Bearer ' . $c['token'],
    'x-nos-user-uid' => $c['uid'] ?? null, 'x-nos-user-groups' => $c['groups'] ?? null]);
  $req = new Nette\Http\Request(new Nette\Http\UrlScript('http://wing/api'), headers: $headers, method: $c['method'] ?? 'POST');
  $res = new Nette\Http\Response;
  $p->injectPrimary($req, $res);
  $params = ['action' => $c['action']] + ($c['params'] ?? []);
  try {
    $r = $p->run(new Nette\Application\Request('Api:' . $c['presenter'], $c['method'] ?? 'POST', $params));
    $payload = $r instanceof Nette\Application\Responses\JsonResponse ? $r->getPayload() : null;
  } catch (Error $e) {
    if (!str_contains($e->getMessage(), 'must not be accessed before initialization')) throw $e;
    $payload = 'reached';
  }
  $out[] = ['code' => $res->getCode(), 'payload' => $payload, 'halt_active' => $pulse->isEmergencyHaltActive(),
            'last_actor' => $pdo->fetchField("SELECT actor_id FROM events WHERE type LIKE 'admin_emergency_%' ORDER BY id DESC LIMIT 1")];
}
echo json_encode($out);
"""


def _run(tmp_path, cases):
    subprocess.run(["php", str(WING / "bin/init-db.php"), f"--data-dir={tmp_path}"], capture_output=True, check=True, timeout=60)
    r = subprocess.run(["php", "-d", "error_reporting=E_ALL", "-r", _HARNESS, str(AUTOLOAD), str(tmp_path / "wing.db"),
                        json.dumps(cases)], capture_output=True, text=True, timeout=120, cwd=WING, check=False)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(r.stdout)


@needs_php
@needs_vendor
def test_the_api_halts_for_the_operator_and_refuses_agents(tmp_path):
    admin = {"uid": "alice", "groups": "nos-admins"}
    got = _run(tmp_path, [
        {"presenter": "Admin", "action": "halt", "token": "agent"},
        {"presenter": "Admin", "action": "halt", "token": "ansible"},
        {"presenter": "Admin", "action": "halt", "token": "bff", "uid": "bob", "groups": "nos-users"},
        {"presenter": "Admin", "action": "halt", "token": "halt"},
        {"presenter": "Admin", "action": "state", "token": "agent", "method": "GET"},
        {"presenter": "Admin", "action": "resume", "token": "bff", **admin},
        {"presenter": "Upgrades", "action": "apply", "token": "halt", "params": {"service": "x", "recipe": "y"}},
    ])
    for i in (0, 1, 2):
        assert got[i]["code"] == 403 and not got[i]["halt_active"], got[i]
        assert "operator decision" in got[i]["payload"]["error"], got[i]
    assert got[3]["code"] == 200 and got[3]["halt_active"], got[3]
    assert got[3]["last_actor"] == "wing-halt" and got[3]["payload"]["jobs_affected"] == 1, got[3]
    assert got[4]["code"] == 200 and got[4]["payload"]["halt_active"] is True, got[4]
    assert got[5]["code"] == 200 and not got[5]["halt_active"], got[5]
    assert got[5]["last_actor"] == "user:alice", "the record names the person, not the token"
    assert got[6]["code"] == 403, f"wing.halt reached another operator verb: {got[6]}"
