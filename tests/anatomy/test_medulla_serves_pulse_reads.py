"""The medulla answers Wing's Pulse reads exactly as PHP does (ssot/doctrine/medulla.md §5).

WHY (row medulla-scheduler, increment d; operator ruling 2026-10-25). The medulla executes, it never
writes the record, so only the GETs of /api/v1/pulse_jobs and /pulse_runs move (medulla_read_routes:
[pulse]); a POST, a finish, run-now, HEAD and /pulse_jobs/due stay PHP's. Parity is measured, not
claimed: the real PulsePresenter (routed by RouterFactory) and the medulla answer the SAME scratch
wing.db for every route x every bearer, and no env VALUE leaves either (withoutSecrets).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import http.server
import importlib.util
import json
import pathlib
import re
import shutil
import subprocess
import threading
import urllib.error
import urllib.request

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("_metrics", REPO / "tests/anatomy/test_medulla_serves_metrics.py")
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)

SECRET = "s3cr3t-value-must-not-leak"


def _render(reads: list[str], routes: list[str] | None = None) -> str:
    env = m.jinja2.Environment(undefined=m.jinja2.StrictUndefined)
    return env.from_string(m.CADDY.read_text(encoding="utf-8")).render(
        wing_log_dir="/x", wing_app_dir="/x", nos_docker_host_ip="127.0.0.1", wing_edge_token="t",
        medulla_routes=routes or [], medulla_read_routes=reads, medulla_http_port=8095)


def test_the_caddyfile_moves_reads_only_when_listed():
    assert "@medulla_read" not in _render([]), "an empty medulla_read_routes still hands a read away"
    site = _render(["pulse"]).split(":9000 {", 1)[1]
    block = re.search(r"@medulla_read_pulse \{(.*?)\n    \}", site, re.S).group(1)
    assert "method GET\n" in block and "HEAD" not in block, block
    assert "not query since=*" in block and "not query until=*" in block, block
    assert site.index("handle @medulla_read_pulse") < site.index("php_server")
    with pytest.raises(m.jinja2.UndefinedError):
        _render(["nonesuch"])
    assert _render(["pulse"], ["metrics"]).count("reverse_proxy 127.0.0.1:8095") == 2, "metrics' handle changed"


class _Echo(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"medulla")

    def log_message(self, *a):
        pass


#: (method, path) -> who answers once medulla_read_routes is [pulse].
ROUTING = [("GET", "/api/v1/pulse_jobs", "medulla"), ("GET", "/api/v1/pulse_runs", "medulla"),
           ("GET", "/api/v1/pulse_runs?limit=3&job_id=a", "medulla"), ("GET", "/api/v1/pulse_runs/summary", "medulla"),
           ("GET", "/api/v1/pulse_runs/r1", "medulla"),
           ("POST", "/api/v1/pulse_runs", "php"), ("POST", "/api/v1/pulse_jobs", "php"),
           ("POST", "/api/v1/pulse_runs/r1/finish", "php"), ("GET", "/api/v1/pulse_runs/r1/finish", "php"),
           ("POST", "/api/v1/pulse_jobs/a:b/run-now", "php"), ("DELETE", "/api/v1/pulse_jobs/a:b", "php"),
           ("HEAD", "/api/v1/pulse_jobs", "php"), ("GET", "/api/v1/pulse_jobs/due", "php"),
           ("GET", "/api/v1/pulse_jobs/a:b", "php"), ("GET", "/api/v1/pulse_runs?since=2026-01-01", "php"),
           ("GET", "/api/v1/pulse_runs?limit=2&until=now", "php"), ("GET", "/api/v1/pulse_runsx", "php"),
           ("GET", "/api/v1/pulse_runs/", "php"), ("GET", "/api/v1/dashboard/summary", "php")]


@pytest.mark.skipif(not m._frankenphp(), reason="no frankenphp binary runs the Caddyfile")
@pytest.mark.parametrize("reads", [[], ["pulse"]])
def test_caddy_sends_only_the_reads_to_the_medulla(tmp_path, reads):
    (tmp_path / "www").mkdir()
    (tmp_path / "www/index.php").write_text("<?php echo 'php';")
    stub = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Echo)
    threading.Thread(target=stub.serve_forever, daemon=True).start()
    port = m._free_port()
    env = m.jinja2.Environment(undefined=m.jinja2.StrictUndefined)
    conf = env.from_string(m.CADDY.read_text(encoding="utf-8")).render(
        wing_log_dir=str(tmp_path), wing_app_dir=str(tmp_path), nos_docker_host_ip="127.0.0.1", wing_edge_token="t",
        medulla_routes=[], medulla_read_routes=reads, medulla_http_port=stub.server_address[1])
    (tmp_path / "Caddyfile").write_text(conf.replace(":9000 {", f":{port} {{"))  # never the live Wing's :9000
    p = subprocess.Popen([m._frankenphp(), "run", "--config", str(tmp_path / "Caddyfile")],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        m._wait(p, port, "frankenphp served the rendered Caddyfile")
        for method, path, who in ROUTING:
            req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method, data=b"{}" if method == "POST" else None)
            try:
                with urllib.request.urlopen(req, timeout=10) as r:
                    body = r.read().decode()
            except urllib.error.HTTPError as e:
                body = e.read().decode()
            want = who if reads else "php"
            got = "" if method == "HEAD" else body
            assert got == ("" if method == "HEAD" else want), f"{method} {path} reached {got!r}, not {want}"
        if reads:  # HEAD is PHP's: the stub has no do_HEAD, so a HEAD sent to it would 501
            req = urllib.request.Request(f"http://127.0.0.1:{port}/api/v1/pulse_jobs", method="HEAD")
            assert urllib.request.urlopen(req, timeout=10).status == 200
            req = urllib.request.Request(f"http://127.0.0.1:{port}/api/v1/pulse_jobs", headers={"Content-Type": "multipart/form-data"})
            with pytest.raises(urllib.error.HTTPError) as e:
                urllib.request.urlopen(req, timeout=10)
            assert e.value.code == 415, "a multipart body reached the medulla before Wing's 415"
    finally:
        p.kill()
        p.wait()
        stub.shutdown()


# ── PHP and the medulla over one scratch wing.db ────────────────────────────

_PHP = r"""
$composer = require $argv[1];
$home = dirname(realpath($argv[1]), 2);
spl_autoload_register(function ($c) use ($composer, $home) {   // this tree's app/, even with vendor symlinked
  $own = getcwd() . '/app/' . str_replace('\\', '/', substr($c, 4)) . '.php';
  $f = realpath((string) $composer->findFile($c));
  if (str_starts_with($c, 'App\\') && is_file($own)) require $own;
  elseif ($f && str_starts_with($f, $home . '/app/')) require getcwd() . substr($f, strlen($home));
}, prepend: true);
$pdo = new Nette\Database\Connection('sqlite:' . $argv[2]);
$cache = new Nette\Caching\Storages\DevNullStorage;
$structure = new Nette\Database\Structure($pdo, $cache);
$db = new Nette\Database\Explorer($pdo, $structure, new Nette\Database\Conventions\DiscoveredConventions($structure), $cache);
$router = App\Core\RouterFactory::createRouter();
$out = [];
foreach (json_decode($argv[3], true) as $c) {
  $req = new Nette\Http\Request(new Nette\Http\UrlScript('http://wing' . $c['url'], '/'),
    headers: array_change_key_case($c['headers'], CASE_LOWER), method: 'GET');
  $params = $router->match($req);
  $name = $params['presenter'];
  unset($params['presenter']);
  $p = new App\Presenters\Api\PulsePresenter(new App\Model\PulseRepository($db),
    new App\Model\NotificationRepository($db), new App\Model\EventRepository($db));
  $p->tokenRepo = new App\Model\TokenRepository($db);
  $p->autoCanonicalize = false;
  $res = new Nette\Http\Response;
  $p->injectPrimary($req, $res);
  $r = $p->run(new Nette\Application\Request($name, 'GET', $params));
  $out[] = ['code' => $res->getCode(), 'body' => Nette\Utils\Json::encode($r->getPayload())];
}
echo json_encode($out);
"""

#: plaintext -> (name, scopes, active)
TOKENS = {"read": ("conductor", "wing.read", 1), "write": ("cortex-executor", "wing.write", 1),
          "null": ("scout", None, 1), "blank": ("blank", "", 1), "halt": ("wing-halt", "wing.halt", 1),
          "run": ("medulla", "pulse.run", 1), "gone": ("retired", "wing.read", 0),
          "bff": ("face-bff", "wing.operator,wing.write", 1), "thal": ("thalamus", "wing.write", 1)}

AUTH = {
    "no bearer": {}, "basic": {"Authorization": "Basic cmVhZA=="}, "lowercase bearer": {"Authorization": "bearer read"},
    "unknown token": {"Authorization": "Bearer nope"}, "inactive token": {"Authorization": "Bearer gone"},
    "wing.read": {"Authorization": "Bearer read"}, "wing.write": {"Authorization": "Bearer write"},
    "NULL scopes": {"Authorization": "Bearer null"}, "empty scopes": {"Authorization": "Bearer blank"},
    "wing.halt only": {"Authorization": "Bearer halt"}, "pulse.run only": {"Authorization": "Bearer run"},
    "face-bff, no uid": {"Authorization": "Bearer bff"},
    "face-bff, uid not canonical": {"Authorization": "Bearer bff", "X-Nos-User-Uid": "Alice", "X-Nos-User-Groups": "nos-admins"},
    "face-bff, tier 3": {"Authorization": "Bearer bff", "X-Nos-User-Uid": "alice", "X-Nos-User-Groups": "nos-users"},
    "face-bff, tier 1": {"Authorization": "Bearer bff", "X-Nos-User-Uid": "alice", "X-Nos-User-Groups": "x|Nos-Admins"},
    "thalamus, no uid": {"Authorization": "Bearer thal"},
    "thalamus, a person": {"Authorization": "Bearer thal", "X-Nos-User-Uid": "alice", "X-Nos-User-Groups": "nos-admins"},
}

ROUTES = ["/api/v1/pulse_jobs", "/api/v1/pulse_runs", "/api/v1/pulse_runs?limit=2", "/api/v1/pulse_runs?limit=abc",
          "/api/v1/pulse_runs?limit=", "/api/v1/pulse_runs?limit=999", "/api/v1/pulse_runs?limit=-5",
          "/api/v1/pulse_runs?limit=3abc", "/api/v1/pulse_runs?limit=1e1&limit=4", "/api/v1/pulse_runs?job_id=p%3Aa",
          "/api/v1/pulse_runs?job_id=", "/api/v1/pulse_runs?failed=1", "/api/v1/pulse_runs?failed=true",
          "/api/v1/pulse_runs?failed=yes", "/api/v1/pulse_runs?job_id=p:a&failed=1&limit=1",
          "/api/v1/pulse_runs?since=&until=", "/api/v1/pulse_runs/summary", "/api/v1/pulse_runs/r3",
          "/api/v1/pulse_runs/r%206", "/api/v1/pulse_runs/nope"]


def _iso(delta_h: float) -> str:
    t = dt.datetime.now(dt.timezone.utc).replace(microsecond=0) - dt.timedelta(hours=delta_h)
    return t.strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _seed(db: pathlib.Path) -> None:
    q = lambda v: "NULL" if v is None else "'" + str(v).replace("'", "''") + "'"  # noqa: E731
    sql = [f"INSERT INTO api_tokens (token, name, scopes, active) VALUES ({q(hashlib.sha256(t.encode()).hexdigest())}, "
           f"{q(n)}, {q(s)}, {a});" for t, (n, s, a) in TOKENS.items()]
    jobs = [("p:a", "p", "a", json.dumps({"WING_API_TOKEN": SECRET, "PLAIN": "x"}), "[3]", "security", 0, None, None),
            ("p:b", "p", "b", "{}", None, None, 1, "operator", None),
            ("q:c", "q", "c", "[]", '["7", 0]', None, 0, None, None),
            ("q:z", "q", "z", "not json", None, None, 0, None, None),
            ("q:gone", "q", "gone", json.dumps({"K": SECRET}), None, None, 0, None, "2026-10-01")]
    for jid, plug, name, env, fec, cat, paused, reason, removed in jobs:
        sql.append("INSERT INTO pulse_jobs (id, plugin_name, job_name, command, args_json, env_json, schedule, "
                   "findings_exit_codes, category, paused, paused_reason, next_fire_at, removed_at) VALUES "
                   f"({q(jid)}, {q(plug)}, {q(name)}, '/usr/bin/true', '[\"--x=a/b\"]', {q(env)}, '*/5 * * * *', "
                   f"{q(fec)}, {q(cat)}, {paused}, {q(reason)}, {q(_iso(-1))}, {q(removed)});")
    runs = [("r1", "p:a", 3, 0), ("r2", "p:a", 2, 3), ("r3", "p:a", 1, 1), ("r4", "p:a", 0.5, 1),
            ("r5", "p:b", 48, 0), ("r 6", "p:b", 0.2, None), ("r7", "q:c", 5, 7), ("r8", "q:c", 5, 2),
            ("r9", "x:orphan", 4, 0)]
    for rid, job, ago, code in runs:
        sql.append("INSERT INTO pulse_runs (run_id, job_id, fired_at, finished_at, exit_code, duration_ms, stdout_tail, "
                   f"stderr_tail, actor_id) VALUES ({q(rid)}, {q(job)}, {q(_iso(ago))}, "
                   f"{q(None if code is None else _iso(ago - 0.01))}, {q(code) if code is None else code}, "
                   f"{'NULL' if code is None else 1200}, 'héllo ✓ a/b', {q(None if code in (0, None) else 'boom')}, 'pulse');")
    subprocess.run(["sqlite3", str(db)], input="\n".join(sql), text=True, check=True)


def _medulla_get(port: int, url: str, headers: dict) -> tuple[int, str, str]:
    req = urllib.request.Request(f"http://127.0.0.1:{port}{url}", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.headers.get("Content-Type", ""), r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", ""), e.read().decode()


def _comparable(body: str) -> object:
    doc = json.loads(body)
    if isinstance(doc, dict) and "generated_at" in doc:
        assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00", doc.pop("generated_at")), body
    return doc


@m.needs_cargo
@pytest.mark.skipif(not shutil.which("php"), reason="php runs Wing")
@pytest.mark.skipif(not m.AUTOLOAD.exists(), reason="wing vendor/autoload.php missing (composer install)")
@pytest.mark.skipif(not shutil.which("sqlite3"), reason="sqlite3 seeds the scratch wing.db")
def test_php_and_the_medulla_answer_every_read_the_same(tmp_path):
    subprocess.run(["php", str(m.WING / "bin/init-db.php"), f"--data-dir={tmp_path}"], capture_output=True, check=True, timeout=60)
    db = tmp_path / "wing.db"
    _seed(db)
    cases = [{"url": u, "headers": h, "auth": a} for u in ROUTES for a, h in AUTH.items()]
    r = subprocess.run(["php", "-d", "error_reporting=E_ALL", "-r", _PHP, str(m.AUTOLOAD), str(db), json.dumps(cases)],
                       capture_output=True, text=True, timeout=300, check=False, cwd=m.WING)
    assert r.returncode == 0, (r.stdout + r.stderr)[-4000:]
    php = json.loads(r.stdout)
    proc, port = m._serve(m._medulla(tmp_path), db)
    try:
        got = [_medulla_get(port, c["url"], c["headers"]) for c in cases]
    finally:
        proc.kill()
        proc.wait()
    paths = m.yaml.safe_load(m.OPENAPI.read_text(encoding="utf-8"))["paths"]
    codes: dict[tuple[str, int], int] = {}
    for c, want, (code, ctype, body) in zip(cases, php, got):
        where = f"{c['url']} as {c['auth']}"
        path = c["url"].split("?")[0]
        op = paths.get(path) or paths["/api/v1/pulse_runs/{id}"]
        assert str(code) in op["get"]["responses"], f"{where}: {code} is not in wing.openapi.yml"
        assert SECRET not in body and SECRET not in want["body"], f"an env VALUE left on {where}"
        assert code == want["code"], f"{where}: medulla {code} {body[:300]} / php {want['code']} {want['body'][:300]}"
        assert ctype == "application/json; charset=utf-8", f"{where}: {ctype}"
        assert _comparable(body) == _comparable(want["body"]), f"{where}:\nmedulla {body[:1500]}\nphp     {want['body'][:1500]}"
        codes[(c["auth"], code)] = codes.get((c["auth"], code), 0) + 1
    # The seed reaches every outcome; a fixture gone blind would pass the comparison vacuously.
    assert {code for _, code in codes} == {200, 401, 403, 404}, codes
    jobs = json.loads(got[ROUTES.index("/api/v1/pulse_jobs") * len(AUTH) + list(AUTH).index("wing.read")][2])["jobs"]
    assert jobs["p:a"]["env_keys"] == ["WING_API_TOKEN", "PLAIN"] and "env_json" not in jobs["p:a"], jobs["p:a"]
    assert "q:gone" not in jobs, "a removed job is listed"
