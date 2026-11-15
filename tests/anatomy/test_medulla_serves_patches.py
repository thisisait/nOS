"""The medulla answers GET /api/v1/patches[/<id>] and /patches/history as Api\\PatchesPresenter does (ssot/doctrine/medulla.md §5).

WHY (read set [patches]). The patch catalogue and its apply history are estate-wide and the presenter opens no
face-bff door, so a person at any tier is refused. The list drops status and component_id on empty() ('' and "0"),
applies a limit only above 0 (clamped to 500; else every row), and /patches/0 lists. History filters on "0", clamps
1..500 and decodes `record` only for a non-empty raw record. /patches/history is its own action before /<id>.
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
# The read actions touch the repository's $db alone: BoneClient and EventRepository (plan, apply, events) are never built.
_PHP = (_pre + "  $rc = new ReflectionClass(App\\Presenters\\Api\\PatchesPresenter::class);\n  $p = $rc->newInstanceWithoutConstructor();\n"
        + "  $repo = (new ReflectionClass(App\\Model\\PatchRepository::class))->newInstanceWithoutConstructor();\n"
        + "  (new ReflectionClass(App\\Model\\PatchRepository::class))->getProperty('db')->setValue($repo, $db);\n"
        + "  $rc->getProperty('patches')->setValue($p, $repo);\n"
        + "  (new ReflectionMethod(Nette\\Application\\UI\\Presenter::class, '__construct'))->invoke($p);\n"
        + _rest[_rest.index("  $p->tokenRepo"):])

#: id, finding_ref, component_id, description, status, created_at. A patch named "history" is the arm-order decoy.
PATCHES = [("PATCH-001", "CVE-1", "traefik", "Oprava ✓", "draft", "2026-10-01 10:00:00"),
           ("PATCH-002", None, "traefik", None, "applied", "2026-10-01 10:00:00"),
           ("PATCH-003", "GHSA-x", "grafana", "", "draft", "2026-10-02 10:00:00"), ("0", "id zero", "0", "zero", "0", "2026-10-03 10:00:00"),
           ("a b", "space", "comp with space", "d", "upstreamed", "2026-10-04 10:00:00"), ("résumé", "u", None, "d", "draft", "2026-10-04 10:00:00"),
           ("history", "decoy", "traefik", "a patch whose id is the history path", "draft", "2026-10-05 10:00:00")]
#: patch_id, component_id, applied_at, success, rolled_back, raw_record_json
APPLIED = [("PATCH-001", "traefik", "2026-10-05T10:00:00+00:00", 1, 0, '{"rc":0,"msg":"Hotovo ✓","steps":[{"a":1},{}]}'),
           ("PATCH-001", "traefik", "2026-10-05T10:00:00+00:00", 0, 1, "not json"), ("PATCH-002", "grafana", "2026-10-06T10:00:00+00:00", 1, 0, None),
           ("PATCH-003", None, "2026-10-07T10:00:00+00:00", 1, 0, ""), ("0", "0", "2026-10-08T10:00:00+00:00", 1, 0, "0"),
           ("PATCH-009", "traefik", "2026-10-09T10:00:00+00:00", 1, 0, "{}"),
           ("PATCH-009", "traefik", "2026-10-09T10:00:00+00:00", 1, 0, '{"0":"a","1":"b"}'),
           ("PATCH-010", "x", "2026-10-10T10:00:00+00:00", 1, 0, "[]"), ("PATCH-011", "x", "2026-10-10T10:00:00+00:00", 1, 0, "null"),
           ("PATCH-012", "x", "2026-10-11T10:00:00+00:00", 1, 0, '"str"')]
BULK = 620  # more than the 500 ceiling, equal created_at / applied_at by turns: the order of ties is compared
P, H = "/api/v1/patches", "/api/v1/patches/history"
URLS = [P] + [f"{P}?{q}" for q in (
    "status=draft", "status=applied", "status=0", "status=", "status=nope", "status=DRAFT", "component_id=traefik", "component_id=0",
    "component_id=", "component_id=comp+with+space", "status=draft&component_id=traefik", "limit=0", "limit=1", "limit=2", "limit=501",
    "limit=9999", "limit=abc", "limit=3abc", "limit=", "limit=-3", "limit=1e1", "limit=%202", "limit=1&limit=4", "status=draft&limit=2",
    "patch_id=PATCH-001", "sort=x")] + [
    f"{P}/PATCH-001", f"{P}/PATCH-003", f"{P}/NOPE", f"{P}/a%20b", f"{P}/r%C3%A9sum%C3%A9", f"{P}/patch-001", f"{P}/0",
    f"{P}/0?status=applied&limit=1", f"{P}/PATCH-002?status=draft", H] + [f"{H}?{q}" for q in (
        "patch_id=PATCH-001", "patch_id=0", "patch_id=", "patch_id=nope", "component_id=traefik", "component_id=0", "component_id=",
        "patch_id=PATCH-009&component_id=traefik", "limit=0", "limit=1", "limit=3", "limit=501", "limit=abc", "limit=-5", "limit=",
        "limit=2&patch_id=PATCH-001", "limit=20", "status=draft")]
EVERY_BEARER = {P, f"{P}/PATCH-001", H}  # each action once
#: The matcher keeps these away; the medulla hands them back too (404 at its door).
HANDED_BACK = [f"{P}/PATCH-001/events", f"{P}/PATCH-001/plan", f"{P}/PATCH-001/apply", f"{P}/", f"{P}x", f"{H}/x", "/api/v1/pentest/patches"]
WRITES = [("POST", P), ("PUT", f"{P}/PATCH-001"), ("POST", f"{P}/PATCH-001/plan"), ("POST", f"{P}/PATCH-001/apply")]


def _seed_patches(db: pathlib.Path) -> None:
    q = lambda v: "NULL" if v is None else (str(v) if isinstance(v, int) else "'" + str(v).replace("'", "''") + "'")  # noqa: E731
    sql = ["DELETE FROM patches;", "DELETE FROM patches_applied;"]
    sql += [f"INSERT INTO patches (id, finding_ref, component_id, description, status, created_at) VALUES ({', '.join(q(v) for v in r)});"
            for r in PATCHES]
    sql += [f"INSERT INTO patches_applied (patch_id, component_id, applied_at, success, rolled_back, raw_record_json) "
            f"VALUES ({', '.join(q(v) for v in r)});" for r in APPLIED]
    sql.append(f"WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < {BULK}) INSERT INTO patches "
               "(id, component_id, status, created_at) SELECT 'BULK-' || printf('%04d', (i * 7919) % 1000 * 10 + i % 10), "
               "CASE i % 3 WHEN 0 THEN 'traefik' WHEN 1 THEN 'grafana' ELSE NULL END, CASE i % 2 WHEN 0 THEN 'draft' ELSE 'applied' END, "
               "'2026-09-0' || (1 + i % 2) || ' 00:00:00' FROM n;")
    sql.append(f"WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < {BULK}) INSERT INTO patches_applied "
               "(patch_id, component_id, applied_at, success) SELECT 'BULK-' || (i % 7), 'bulk', '2026-09-0' || (1 + i % 3) || 'T00:00:00+00:00', 1 FROM n;")
    subprocess.run(["sqlite3", str(db)], input="\n".join(sql), text=True, check=True)


def _status(port: int, method: str, url: str) -> int:
    req = urllib.request.Request(f"http://127.0.0.1:{port}{url}", method=method, data=b"{}", headers={"Authorization": "Bearer write"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def test_the_caddyfile_moves_only_the_patches_gets():
    block = re.search(r"@medulla_read_patches \{(.*?)\n    \}", p._render(["patches"]), re.S).group(1).split()
    assert block == ["method", "GET", "path_regexp", "^/api/v1/patches(/[^/]+)?$"], block
    rx = re.compile(block[3])
    for path in (P, f"{P}/PATCH-001", H, f"{P}/0", f"{P}/a%20b"):
        assert rx.search(path), path
    for path in HANDED_BACK:
        assert not rx.search(path), path
    assert "@medulla_read_patches" not in p._render(["remediation", "security"])


@m.needs_cargo
@pytest.mark.skipif(not shutil.which("php"), reason="php runs Wing")
@pytest.mark.skipif(not m.AUTOLOAD.exists(), reason="wing vendor/autoload.php missing (composer install)")
@pytest.mark.skipif(not shutil.which("sqlite3"), reason="sqlite3 seeds the scratch wing.db")
def test_php_and_the_medulla_answer_every_patches_read_the_same(tmp_path, monkeypatch):
    monkeypatch.setenv("NOS_HALT_FILE", str(tmp_path / "halt"))
    subprocess.run(["php", str(m.WING / "bin/init-db.php"), f"--data-dir={tmp_path}"], capture_output=True, check=True, timeout=60)
    db = tmp_path / "wing.db"
    p._seed(db)
    _seed_patches(db)
    cases = [{"url": u, "headers": h, "auth": a} for u in URLS for a, h in p.AUTH.items() if u in EVERY_BEARER or a == "wing.read"]
    exe = m._medulla(tmp_path)
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    proc, port = m._serve(exe, db)
    try:
        got = [p._medulla_get(port, c["url"], c["headers"]) for c in cases]
        handed_back = [p._medulla_get(port, u, p.AUTH["wing.read"])[0] for u in HANDED_BACK]
        writes = [_status(port, method, u) for method, u in WRITES]
    finally:
        m._stop(proc)
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before, "a medulla read changed wing.db"
    assert handed_back == [404] * len(HANDED_BACK), f"the medulla answered a path PHP keeps: {handed_back}"
    assert writes == [404] * len(WRITES), f"the medulla answered a write PHP keeps: {writes}"
    r = subprocess.run(["php", "-d", "error_reporting=E_ALL", "-r", _PHP, str(m.AUTOLOAD), str(db), json.dumps(cases)],
                       capture_output=True, text=True, timeout=300, check=False, cwd=m.WING)
    assert r.returncode == 0, (r.stdout + r.stderr)[-4000:]
    php = json.loads(r.stdout)
    paths = m.yaml.safe_load(m.OPENAPI.read_text(encoding="utf-8"))["paths"]
    codes: dict[str, set[int]] = {}
    for c, want, (code, ctype, body) in zip(cases, php, got):
        where = f"{c['url']} as {c['auth']}"
        base = c["url"].split("?")[0]
        op = paths[base if base in (P, H) else P + "/{id}"]
        assert str(code) in op["get"]["responses"], f"{where}: {code} is not in wing.openapi.yml"
        assert (code, ctype) == (want["code"], "application/json; charset=utf-8"), f"{where}: medulla {code} {ctype} {body[:300]} / php {want}"
        # Parsed JSON keeps list ORDER: the order of ties is the claim.
        assert json.loads(body) == json.loads(want["body"]), f"{where}:\nmedulla {body[:1500]}\nphp     {want['body'][:1500]}"
        codes.setdefault(c["auth"], set()).add(code)
    # The seed reaches every outcome; a fixture gone blind would pass the comparison vacuously.
    assert set().union(*codes.values()) == {200, 401, 403, 404}, codes
    assert (codes["face-bff, tier 1"], codes["face-bff, tier 3"], codes["thalamus, a person"]) == ({403}, {403}, {403}), codes
    p._intents_refused(cases, got)
    read = [i for i, c in enumerate(cases) if c["auth"] == "wing.read"]
    seen = lambda url: json.loads(got[read[URLS.index(url)]][2])  # noqa: E731
    total = len(PATCHES) + BULK
    every = seen(P)["patches"]
    assert len(every) == total and [r["created_at"] for r in every] == sorted((r["created_at"] for r in every), reverse=True)
    for q in ("limit=0", "limit=abc", "limit=", "limit=-3", "status=0", "component_id=0"):
        assert len(seen(f"{P}?{q}")["patches"]) == total, f"{q}: no limit and a dropped filter are every row"
    assert len(seen(f"{P}?limit=9999")["patches"]) == 500 and len(seen(f"{P}?limit=2")["patches"]) == 2, "a positive limit clamps to 500"
    assert seen(f"{P}/0")["patches"] == every, "/patches/0 lists, as PHP's truth test does"
    assert seen(f"{P}/a%20b")["id"] == "a b" and seen(f"{P}/PATCH-002?status=draft")["id"] == "PATCH-002"
    assert seen(f"{P}/NOPE")["error"] == "Patch not found" and seen(f"{P}/patch-001")["error"] == "Patch not found"
    h = seen(H)["items"]
    assert len(h) == 50 and [i["applied_at"] for i in h] == sorted((i["applied_at"] for i in h), reverse=True), "history: newest 50"
    assert "id" not in seen(H) and seen(f"{H}?status=draft")["items"] == h, "/patches/history reached the id arm"
    assert len(seen(f"{H}?limit=501")["items"]) == 500 and [len(seen(f"{H}?{q}")["items"]) for q in ("limit=abc", "limit=-5", "limit=0")] == [1, 1, 1]
    one = {i["raw_record_json"]: i for i in seen(f"{H}?limit=20")["items"] if not i["patch_id"].startswith("BULK")}
    assert one["not json"]["record"] is None and "record" not in one[None] and "record" not in one[""] and "record" not in one["0"]
    assert one["{}"]["record"] == [] and one['{"0":"a","1":"b"}']["record"] == ["a", "b"] and one['"str"']["record"] == "str"
    assert [i["patch_id"] for i in seen(f"{H}?patch_id=0")["items"]] == ["0"], "a history filter of 0 filters"
