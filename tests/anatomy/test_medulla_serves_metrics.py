"""The medulla serves /api/v1/metrics behind Wing's Caddy seam (ssot/doctrine/medulla.md §5).

WHY (row medulla-first-route-metrics). The first route through the strangler seam: a prefix in
medulla_routes renders one Caddy `handle /api/v1/<prefix>*` that proxies to the medulla's loopback
door; everything else still reaches PHP. A moved prefix is whole, or Caddy's first match shadows a
sibling Nette route. The medulla enforces what PHP does today: anonymous read, loopback only.

Every run takes a scratch wing.db and a free port: nothing here reaches the live :9000 or wing.db.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request

import jinja2
import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
CADDY = REPO / "roles/pazny.wing/templates/wing.Caddyfile.j2"
OPENAPI = REPO / "files/anatomy/contracts/wing.openapi.yml"
WS = REPO / "files/anatomy/thalamus"
WING = REPO / "files/anatomy/wing"
AUTOLOAD = WING / "vendor/autoload.php"
THALAMUS_TPL = REPO / "roles/pazny.thalamus/templates"


def _render(routes: list[str]) -> str:
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    return env.from_string(CADDY.read_text(encoding="utf-8")).render(
        wing_log_dir="/x", wing_app_dir="/x", nos_docker_host_ip="127.0.0.1", wing_edge_token="t",
        medulla_routes=routes, medulla_http_port=8095)


def _default_config() -> dict:
    import sys
    sys.path.insert(0, str(REPO / "tools"))
    import nos_identity
    return nos_identity.default_config()


def test_the_caddyfile_hands_a_moved_prefix_to_the_medulla():
    site = _render(["metrics"]).split(":9000 {", 1)[1]
    m = re.search(r"^\s*handle /api/v1/metrics\* \{[^{}]*(?:\{[^{}]*\}[^{}]*)*reverse_proxy 127\.0\.0\.1:8095\s*\}", site, re.M)
    assert m, "no `handle /api/v1/metrics*` block proxying to the medulla in Wing's site"
    assert site.index("bind 127.0.0.1") < m.start() < site.index("php_server"), "the handle is not before php_server"
    assert "handle /api/v1/" not in _render([]), "an empty medulla_routes still hands a prefix away"


def _frankenphp():
    return shutil.which("frankenphp") or next(
        (str(p) for p in [pathlib.Path.home() / ".local/bin/frankenphp"] if p.exists()), None)


def _handlers(routes: list) -> list[dict]:
    """Caddy's real evaluation order, subroutes inlined (Caddy sorts directives; file order lies)."""
    out = []
    for r in routes:
        for h in r.get("handle", []):
            out += _handlers(h["routes"]) if h["handler"] == "subroute" else [h]
    return out


@pytest.mark.skipif(not _frankenphp(), reason="no frankenphp binary adapts the Caddyfile")
def test_the_multipart_415_runs_before_a_moved_prefix(tmp_path):
    (tmp_path / "Caddyfile").write_text(_render(["metrics"]))
    r = subprocess.run([_frankenphp(), "adapt", "--config", str(tmp_path / "Caddyfile")],
                       capture_output=True, text=True, timeout=60, check=False)
    assert r.returncode == 0, r.stderr[-2000:]
    order = [h["handler"] if h.get("status_code") != 415 else "415"
             for h in _handlers(json.loads(r.stdout)["apps"]["http"]["servers"]["srv0"]["routes"])]
    assert "reverse_proxy" in order and "415" in order, order
    assert order.index("415") < order.index("reverse_proxy"), f"a multipart body reaches the medulla before Wing's 415: {order}"


def test_a_moved_prefix_is_whole():
    paths = list(yaml.safe_load(OPENAPI.read_text(encoding="utf-8"))["paths"])
    for prefix in {*_default_config().get("medulla_routes", []), "metrics"}:
        base = f"/api/v1/{prefix}"
        bad = [p for p in paths if p.startswith(base) and p != base and not p.startswith(base + "/")]
        assert not bad, f"handle {base}* would shadow sibling Nette routes {bad}"


# ── the medulla, run ────────────────────────────────────────────────────────

needs_cargo = pytest.mark.skipif(not shutil.which("cargo"), reason="cargo builds the medulla")


def _medulla(tmp: pathlib.Path) -> pathlib.Path:
    # The caller's CARGO_TARGET_DIR, else the workspace's own (gitignored) target: a home path
    # baked in here failed every Linux CI runner (2026-10-23, "failed to create /Users/pazny").
    target = pathlib.Path(os.environ.get("CARGO_TARGET_DIR") or WS / "target")
    r = subprocess.run(["cargo", "build", "--locked", "-p", "medulla"], cwd=WS,
                       env={**os.environ, "CARGO_TARGET_DIR": str(target)},
                       capture_output=True, text=True, timeout=1800, check=False)
    assert r.returncode == 0, r.stderr[-4000:]
    # ponytail: a shared target dir; copied at once so a sibling build cannot swap it mid-test.
    exe = tmp / "medulla"
    shutil.copy2(target / "debug/medulla", exe)
    return exe


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _serve(exe: pathlib.Path, db: pathlib.Path):
    port = _free_port()
    p = subprocess.Popen([str(exe), "wing", "serve", "--db", str(db), "--port", str(port)],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    _wait(p, port, "the medulla answered /api/v1/metrics")
    return p, port


def _wait(p: subprocess.Popen, port: int, what: str) -> None:
    for _ in range(100):
        if p.poll() is not None:
            break
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.1).close()
            return
        except OSError:
            time.sleep(0.05)
    p.kill()
    out, _ = p.communicate()
    pytest.fail(f"{what}: no (exit {p.returncode}) {out}")


def _get(port: int, path: str) -> tuple[int, str, str]:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=10) as r:
            return r.status, r.headers.get("Content-Type", ""), r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", ""), e.read().decode()


def _seed(db: pathlib.Path) -> None:
    rows = [("e2e_journey_end", {"journey": "login", "status": "pass"}, "2026-10-20T10:00:00Z"),
            ("e2e_journey_end", {"journey": "login", "status": "pass"}, "2026-10-21T11:30:00Z"),
            ("e2e_journey_end", {"journey": 'we"ird\\na\nme', "status": "fail"}, "2026-10-21T12:00:00Z"),
            ("e2e_journey_end", {"status": "fail"}, "2026-10-21T12:00:00Z"),
            ("e2e_journey_step", {"journey": "login", "step": "open", "status": "pass", "duration_ms": 120}, "2026-10-21T11:29:00Z"),
            ("e2e_journey_step", {"journey": "login", "step": "open", "status": "pass", "duration_ms": 80}, "2026-10-21T11:29:30Z"),
            ("e2e_journey_step", {"journey": "login", "step": "sso", "status": "fail"}, "2026-10-21T11:29:40Z")]
    sql = ["INSERT INTO events (ts, run_id, type, result_json) VALUES ('{}', 'r', '{}', '{}');".format(
        ts, t, json.dumps(rj).replace("'", "''")) for t, rj, ts in rows]
    for jid, paused, reason, removed in (("p:a", 0, None, None), ("p:b", 1, "emergency-halt:x", None),
                                         ("p:c", 1, "operator", None), ("p:gone", 0, None, "2026-10-01")):
        sql.append("INSERT INTO pulse_jobs (id, plugin_name, job_name, command, schedule, paused, paused_reason, removed_at) "
                   f"VALUES ('{jid}', 'p', '{jid}', '/usr/bin/true', '* * * * *', {paused}, "
                   f"{'NULL' if reason is None else repr(reason)}, {'NULL' if removed is None else repr(removed)});")
    subprocess.run(["sqlite3", str(db)], input="\n".join(sql), text=True, check=True)


def _samples(body: str) -> set[str]:
    return {ln for ln in body.splitlines() if ln and not ln.startswith("#")}


_ROUTER = r"""<?php
// The real MetricsPresenter under `php -S` (the CLI SAPI drops every header), over the scratch H_DB.
chdir(getenv('H_WING'));
$composer = require getenv('H_AUTOLOAD');
$home = dirname(realpath(getenv('H_AUTOLOAD')), 2);
spl_autoload_register(function ($c) use ($composer, $home) {   // this tree's app/, even with vendor symlinked
  $own = getcwd() . '/app/' . str_replace('\\', '/', substr($c, 4)) . '.php';
  $f = realpath((string) $composer->findFile($c));
  if (str_starts_with($c, 'App\\') && is_file($own)) require $own;
  elseif ($f && str_starts_with($f, $home . '/app/')) require getcwd() . substr($f, strlen($home));
}, prepend: true);
$pdo = new Nette\Database\Connection('sqlite:' . getenv('H_DB'));
$cache = new Nette\Caching\Storages\DevNullStorage;
$structure = new Nette\Database\Structure($pdo, $cache);
$db = new Nette\Database\Explorer($pdo, $structure, new Nette\Database\Conventions\DiscoveredConventions($structure), $cache);
$p = new App\Presenters\Api\MetricsPresenter($db);
$p->autoCanonicalize = false;
$p->injectPrimary(new Nette\Http\Request(new Nette\Http\UrlScript('http://wing/api/v1/metrics'), method: 'GET'),
                  new Nette\Http\Response);
try {
  $p->run(new Nette\Application\Request('Api:Metrics', 'GET', ['action' => 'default']));
} catch (Nette\Application\AbortException $e) {
}
"""


def _declared_codes() -> set[int]:
    op = yaml.safe_load(OPENAPI.read_text(encoding="utf-8"))["paths"]["/api/v1/metrics"]["get"]
    return {int(c) for c in op["responses"]}


@needs_cargo
@pytest.mark.skipif(not shutil.which("php"), reason="php runs Wing")
@pytest.mark.skipif(not AUTOLOAD.exists(), reason="wing vendor/autoload.php missing (composer install)")
@pytest.mark.skipif(not shutil.which("sqlite3"), reason="sqlite3 seeds the scratch wing.db")
def test_php_and_the_medulla_answer_metrics_the_same(tmp_path):
    subprocess.run(["php", str(WING / "bin/init-db.php"), f"--data-dir={tmp_path}"], capture_output=True, check=True, timeout=60)
    db = tmp_path / "wing.db"
    _seed(db)
    router = tmp_path / "router.php"
    router.write_text(_ROUTER)
    env = {**os.environ, "H_WING": str(WING), "H_AUTOLOAD": str(AUTOLOAD), "H_DB": str(db)}
    php_port = _free_port()
    srv = subprocess.Popen(["php", "-S", f"127.0.0.1:{php_port}", str(router)], cwd=tmp_path, env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        _wait(srv, php_port, "php -S answered")
        php_code, php_type, php_body = _get(php_port, "/api/v1/metrics")
    finally:
        srv.kill()
        srv.wait()
    exe = _medulla(tmp_path)
    proc, port = _serve(exe, db)
    try:
        code, ctype, body = _get(port, "/api/v1/metrics")
    finally:
        proc.kill()
        proc.wait()
    declared = _declared_codes()
    assert php_code in declared and code in declared, (php_code, code, declared, php_body)
    assert code == php_code == 200, php_body
    for t in (php_type, ctype):
        assert t.replace(" ", "").startswith("text/plain;version=0.0.4"), t
    assert _samples(php_body), "the seed produced no PHP samples"
    assert _samples(body) == _samples(php_body), sorted(_samples(body) ^ _samples(php_body))


@needs_cargo
def test_the_medulla_listens_on_loopback_only_and_answers_nothing_else(tmp_path):
    db = tmp_path / "wing.db"
    subprocess.run(["sqlite3", str(db)], input="CREATE TABLE events (ts TEXT, type TEXT, result_json TEXT);"
                   "CREATE TABLE pulse_jobs (id TEXT, paused INT, paused_reason TEXT, removed_at TEXT);",
                   text=True, check=True)
    proc, port = _serve(_medulla(tmp_path), db)
    try:
        lsof = subprocess.run(["lsof", "-nP", "-a", "-p", str(proc.pid), "-iTCP", "-sTCP:LISTEN"],
                              capture_output=True, text=True, check=False).stdout if shutil.which("lsof") else ""
        if lsof:
            assert f"127.0.0.1:{port}" in lsof and f"*:{port}" not in lsof, lsof
        assert _get(port, "/api/v1/admin/state")[0] == 404
        assert _get(port, "/api/v1/metrics")[0] == 200, "no bearer: the scrape is anonymous, as in PHP"
        with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
            s.sendall(b"GET /" + b"a" * 9 * 1024 + b" HTTP/1.1\r\nHost: x\r\n\r\n")
            assert s.recv(64).startswith(b"HTTP/1.1 413"), "a 9 KiB request line was not refused"
    finally:
        proc.kill()
        proc.wait()


# ── the host env ────────────────────────────────────────────────────────────

def _thalamus_env(**over) -> tuple[str, dict]:
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    env.filters["bool"] = bool
    ctx = {"thalamus_launchd_label": "l", "thalamus_bin": "/h/bin/thalamus", "thalamus_home": "/h",
           "thalamus_log_dir": "/h/log", "thalamus_data_dir": "/h/data", "nos_main_checkout": "/repo",
           "nos_tools_venv": "/v", "ansible_facts": {"env": {"HOME": "/h"}}, "keap_proxy_shared_secret": "s",
           "thalamus_shared_socket": "/s", "ansible_managed": "m", "thalamus_roadmap_table_id": "rt",
           "authentik_rbac_tiers": _default_config()["authentik_rbac_tiers"], "thalamus_binding_env": {},
           "wing_data_dir": "/h/wing/app/data", "medulla_http_port": 8095, **over}
    import plistlib
    envfile = env.from_string((THALAMUS_TPL / "thalamus.env.j2").read_text()).render(**ctx)
    plist = plistlib.loads(env.from_string((THALAMUS_TPL / "thalamus.plist.j2").read_text()).render(**ctx).encode())
    return envfile, plist["EnvironmentVariables"]


def test_the_env_carries_the_wing_db_only_when_a_route_moved():
    for routes, user, moved in (([], "", False), (["metrics"], "", True), (["metrics"], "nos", False)):
        envfile, plist = _thalamus_env(medulla_routes=routes, nos_system_user=user)
        lines = set(envfile.splitlines())
        assert ("NOS_WING_DB=/h/wing/app/data/wing.db" in lines) is moved, (routes, user, envfile)
        assert ("MEDULLA_HTTP_PORT=8095" in lines) is moved, (routes, user)
        assert (plist.get("NOS_WING_DB") == "/h/wing/app/data/wing.db") is moved, (routes, user)
        assert (plist.get("MEDULLA_HTTP_PORT") == "8095") is moved, (routes, user)
    envfile, plist = _thalamus_env(medulla_routes=[])
    assert "NOS_WING_DB" not in envfile and "NOS_WING_DB" not in plist, "nos_system_user unset is not an error"


def test_wing_refuses_a_moved_route_under_the_nos_user():
    # fail + literal `when:`, not assert: the profile builder carries `when` literals to its page
    # (tools/profile-builder/rules.py) and refuses an assert it cannot carry.
    tasks = yaml.safe_load((REPO / "roles/pazny.wing/tasks/main.yml").read_text())
    names = [t.get("name", "") for t in tasks]
    guard = next((t for t in tasks if "ansible.builtin.fail" in t and "medulla_routes" in str(t.get("when"))), None)
    assert guard, "no fail ties medulla_routes to nos_system_user"
    assert names.index(guard["name"]) < names.index("[pazny.wing] Render Caddyfile")
    env = jinja2.Environment()
    when = guard["when"]
    fires = lambda **ctx: all(env.from_string("{{ " + c + " }}").render(**ctx) == "True" for c in when)
    assert not fires(medulla_routes=["metrics"]) and not fires(medulla_routes=[], nos_system_user="nos")
    assert fires(medulla_routes=["metrics"], nos_system_user="nos")

