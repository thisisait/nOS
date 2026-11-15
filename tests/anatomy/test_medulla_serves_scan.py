"""The medulla answers GET /api/v1/scan/state and /scan/cycles exactly as Api\\ScanPresenter does (ssot/doctrine/medulla.md §5).

WHY (read set [scan]). The scan cycle state is estate-wide and the presenter opens no face-bff door, so a person at
any tier is refused. State: no config row is [], next_batch decoded and repeated on top, the latest cycle's
completed_at else started_at, probes by cycle_mod. Cycles: (int) limit, default 10, not clamped (0, "abc", '' are an
empty page), batch_components decoded when not NULL. A negative limit is PHP's 500. Eight table shapes, one medulla.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import pathlib
import re
import shutil
import subprocess
import urllib.error
import urllib.request

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("_pulse_reads", REPO / "tests/anatomy/test_medulla_serves_pulse_reads.py")
p = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(p)
m = p.m

_pre, _rest = p._PHP.split("  $p = $name", 1)
_tail = _rest[_rest.index("  $p->tokenRepo"):]
_run = ("  $r = $p->run(new Nette\\Application\\Request($name, 'GET', $params));\n"
        "  $out[] = ['code' => $res->getCode(), 'body' => Nette\\Utils\\Json::encode($r->getPayload())];\n")
assert _run in _tail, "the shared PHP harness changed: re-wrap its run"
# Nette throws on a negative limit (PHP's HTML 500 page): caught as 500, so one run answers every case.
_tail = _tail.replace(_run, "  try {\n" + _run + "  } catch (Nette\\Application\\AbortException $e) { throw $e; }\n"
                      "  catch (Throwable $e) { $out[] = ['code' => 500, 'body' => json_encode(['threw' => $e->getMessage()])]; }\n")
_PHP = _pre + "  $p = new App\\Presenters\\Api\\ScanPresenter(new App\\Model\\ScanStateRepository($db));\n" + _tail

S, C = "/api/v1/scan/state", "/api/v1/scan/cycles"
URLS = [S, f"{S}?limit=1&x=0", C] + [f"{C}?{q}" for q in (
    "limit=0", "limit=1", "limit=3", "limit=10", "limit=9999", "limit=abc", "limit=3abc", "limit=", "limit=1e1", "limit=%202", "limit=1&limit=4",
    "since=x")]
EVERY_BEARER = {S, C}
NEGATIVE = [f"{C}?limit=-5", f"{C}?limit=-1&since=x"]
#: Nothing matches these; the medulla hands them back too (404 at its door).
HANDED_BACK = ["/api/v1/scan/cycle", "/api/v1/scan/config", "/api/v1/scan/rotation", "/api/v1/scan/component/traefik", f"{S}/", f"{C}x",
               "/api/v1/scan", "/api/v1/scan/probe/x/complete"]
WRITES = [("POST", "/api/v1/scan/cycle"), ("PUT", "/api/v1/scan/config"), ("PUT", "/api/v1/scan/rotation"), ("PUT", S), ("POST", C)]
#: batch_components: a list, NULL, undecodable, {}, an int-keyed object, '', the literal null, a scalar, [] and more.
_CYC = ("INSERT INTO scan_cycles (cycle_number, started_at, completed_at, batch_components, notes) VALUES "
        "(1, '2026-10-01 06:00:00', '2026-10-01 06:10:00', '[\"traefik\",\"grafana\"]', 'Poznámka ✓'), "
        "(2, '2026-10-02 06:00:00', '2026-10-02 06:20:00', NULL, NULL), (3, '2026-10-03 06:00:00', '2026-10-03 06:05:00', 'not json', ''), "
        "(4, '2026-10-04 06:00:00', '2026-10-04 06:05:00', '{}', 'x'), (5, '2026-10-05 06:00:00', '2026-10-05 06:05:00', '{\"0\":\"a\",\"1\":\"b\"}', 'x'), "
        "(6, '2026-10-06 06:00:00', '2026-10-06 06:05:00', '', 'x'), (7, '2026-10-07 06:00:00', '2026-10-07 06:05:00', 'null', 'x'), "
        "(8, '2026-10-08 06:00:00', '2026-10-08 06:05:00', '\"str\"', 'x'), (9, '2026-10-09 06:00:00', '2026-10-09 06:05:00', '[]', 'x'), "
        "(10, '2026-10-10 06:00:00', '2026-10-10 06:05:00', '[1]', 'x'), (11, '2026-10-11 06:00:00', '2026-10-11 06:05:00', '[2]', 'x'), "
        "(12, '2026-10-12 06:00:00', {last}, '[\"mariadb\"]', 'running');")
#: cycle_mod ties (two probes at 2): their order is compared too.
_PROBES = ("INSERT INTO attack_probes (cycle_mod, name, description, last_run, findings, completed) VALUES "
           "(2, 'sqli', 'Popis ✓', '2026-10-01', 3, 1), (0, 'xss', NULL, NULL, 0, 0), (2, 'ssrf', '', '2026-10-02', 0, 1), (1, 'authz', 'd', NULL, 1, 0);")
_CONF = "INSERT INTO scan_config (id, batch_size, schedule, last_full_scan, next_batch) VALUES (1, 7, 'hourly', '2026-10-11 06:00:00', {nb});"
_RESET = "DELETE FROM scan_cycles; DELETE FROM attack_probes; DELETE FROM scan_config;"
VARIANTS = {
    "full, latest cycle still running": _RESET + _CYC.replace("{last}", "NULL") + _PROBES + _CONF.replace("{nb}", "'[\"traefik\",\"gitea\"]'"),
    "latest cycle completed, next_batch NULL": _RESET + _CYC.replace("{last}", "'2026-10-12 06:30:00'") + _PROBES + _CONF.replace("{nb}", "NULL"),
    "latest completed_at is '', next_batch not json": _RESET + _CYC.replace("{last}", "''") + _CONF.replace("{nb}", "'not json'"),
    "next_batch is an object": _RESET + _CYC.replace("{last}", "NULL") + _CONF.replace("{nb}", "'{\"a\":1,\"b\":{}}'"),
    "next_batch is a scalar": _RESET + _PROBES + _CONF.replace("{nb}", "'\"str\"'"),
    "next_batch is the literal null": _RESET + _CONF.replace("{nb}", "'null'"),
    "next_batch is ''": _RESET + _CONF.replace("{nb}", "''"),
    "no config row, no cycle, no probe": _RESET,
}


def _status(port: int, method: str, url: str) -> int:
    req = urllib.request.Request(f"http://127.0.0.1:{port}{url}", method=method, data=b"{}", headers={"Authorization": "Bearer write"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def test_the_caddyfile_moves_only_the_scan_gets():
    block = re.search(r"@medulla_read_scan \{(.*?)\n    \}", p._render(["scan"]), re.S).group(1).split()
    assert block == ["method", "GET", "path_regexp", "^/api/v1/scan/(state|cycles)$"], block
    rx = re.compile(block[3])
    assert rx.search(S) and rx.search(C), block
    for path in HANDED_BACK:
        assert not rx.search(path), path
    assert "@medulla_read_scan" not in p._render(["pentest", "patches"])


@m.needs_cargo
@pytest.mark.skipif(not shutil.which("php"), reason="php runs Wing")
@pytest.mark.skipif(not m.AUTOLOAD.exists(), reason="wing vendor/autoload.php missing (composer install)")
@pytest.mark.skipif(not shutil.which("sqlite3"), reason="sqlite3 seeds the scratch wing.db")
def test_php_and_the_medulla_answer_every_scan_read_the_same(tmp_path, monkeypatch):
    monkeypatch.setenv("NOS_HALT_FILE", str(tmp_path / "halt"))
    subprocess.run(["php", str(m.WING / "bin/init-db.php"), f"--data-dir={tmp_path}"], capture_output=True, check=True, timeout=60)
    db = tmp_path / "wing.db"
    p._seed(db)
    cases = [{"url": u, "headers": h, "auth": a} for u in URLS for a, h in p.AUTH.items() if u in EVERY_BEARER or a == "wing.read"]
    neg = [{"url": u, "headers": p.AUTH["wing.read"], "auth": "wing.read"} for u in NEGATIVE]
    paths = m.yaml.safe_load(m.OPENAPI.read_text(encoding="utf-8"))["paths"]
    read = [i for i, c in enumerate(cases) if c["auth"] == "wing.read"]
    exe = m._medulla(tmp_path)
    proc, port = m._serve(exe, db)  # the medulla opens wing.db per request: one process meets every shape
    try:
        assert [p._medulla_get(port, u, p.AUTH["wing.read"])[0] for u in HANDED_BACK] == [404] * len(HANDED_BACK), "the medulla answered a path PHP keeps"
        assert [_status(port, method, u) for method, u in WRITES] == [404] * len(WRITES), "the medulla answered a write PHP keeps"
        for name, sql in VARIANTS.items():
            subprocess.run(["sqlite3", str(db)], input=sql, text=True, check=True)
            before = hashlib.sha256(db.read_bytes()).hexdigest()
            got = [p._medulla_get(port, c["url"], c["headers"]) for c in cases + neg]
            assert hashlib.sha256(db.read_bytes()).hexdigest() == before, f"[{name}] a medulla read changed wing.db"
            r = subprocess.run(["php", "-d", "error_reporting=E_ALL", "-r", _PHP, str(m.AUTOLOAD), str(db), json.dumps(cases + neg)],
                               capture_output=True, text=True, timeout=300, check=False, cwd=m.WING)
            assert r.returncode == 0, (r.stdout + r.stderr)[-4000:]
            php = json.loads(r.stdout)
            for want, (code, _, body) in zip(php[len(cases):], got[len(cases):]):
                assert (want["code"], code) == (500, 500) and "Negative offset or limit" in want["body"] + body, (name, want, code, body)
            php, got = php[:len(cases)], got[:len(cases)]
            codes: dict[str, set[int]] = {}
            for c, want, (code, ctype, body) in zip(cases, php, got):
                where = f"[{name}] {c['url']} as {c['auth']}"
                assert str(code) in paths[c["url"].split("?")[0]]["get"]["responses"], f"{where}: {code} is not in wing.openapi.yml"
                assert (code, ctype) == (want["code"], "application/json; charset=utf-8"), f"{where}: medulla {code} {ctype} {body[:300]} / php {want}"
                # Parsed JSON keeps list ORDER: the order of ties is the claim.
                assert json.loads(body) == json.loads(want["body"]), f"{where}:\nmedulla {body[:1500]}\nphp     {want['body'][:1500]}"
                codes.setdefault(c["auth"], set()).add(code)
            # Neither path has a 404: auth decides the code, the shape decides the body.
            assert set().union(*codes.values()) == {200, 401, 403}, codes
            assert (codes["face-bff, tier 1"], codes["face-bff, tier 3"], codes["thalamus, a person"]) == ({403}, {403}, {403}), codes
            p._intents_refused(cases, got)
            seen = lambda url: json.loads(got[read[URLS.index(url)]][2])  # noqa: E731
            _shape(name, seen)
    finally:
        proc.kill()
        proc.wait()


def _shape(name: str, seen) -> None:
    """The anchors per table shape: a fixture gone blind would pass the comparison vacuously."""
    st, cycles = seen(S), seen(C)["cycles"]
    if name == "no config row, no cycle, no probe":
        assert st == {"config": [], "next_batch": [], "latest_cycle": 0, "latest_cycle_at": None, "attack_probes": []}, st
        assert cycles == [] and seen(f"{C}?limit=9999") == {"cycles": []}
    if name == "full, latest cycle still running":
        assert (st["latest_cycle"], st["latest_cycle_at"]) == (12, "2026-10-12 06:00:00"), "a running cycle reports started_at"
        assert st["next_batch"] == ["traefik", "gitea"] == st["config"]["next_batch"] and st["config"]["batch_size"] == 7
        assert [x["name"] for x in st["attack_probes"]] == ["xss", "authz", "sqli", "ssrf"], "cycle_mod ASC, ties in table order"
        assert [c["cycle_number"] for c in cycles] == list(range(12, 2, -1)), "the newest 10 by cycle_number"
        assert [seen(f"{C}?{q}")["cycles"] for q in ("limit=0", "limit=abc", "limit=")] == [[], [], []], "(int) 0 is an empty page"
        assert len(seen(f"{C}?limit=9999")["cycles"]) == 12 and len(seen(f"{C}?limit=1&limit=4")["cycles"]) == 4, "not clamped; the last one wins"
        bc = {c["cycle_number"]: c["batch_components"] for c in seen(f"{C}?limit=9999")["cycles"]}
        assert [bc[n] for n in range(1, 9)] == [["traefik", "grafana"], None, [], [], ["a", "b"], [], [], "str"]
    if name == "latest cycle completed, next_batch NULL":
        assert st["latest_cycle_at"] == "2026-10-12 06:30:00" and st["config"]["next_batch"] is None and st["next_batch"] == []
    if name.startswith("latest completed_at is ''"):
        assert st["latest_cycle_at"] == "" and st["next_batch"] == [] == st["config"]["next_batch"], "?? skips NULL only"
    if name == "next_batch is an object":
        assert st["next_batch"] == {"a": 1, "b": []} == st["config"]["next_batch"]
    if name == "next_batch is a scalar":
        assert st["next_batch"] == "str" and st["latest_cycle"] == 0 and st["latest_cycle_at"] is None
