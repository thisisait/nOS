"""The medulla answers GET /api/v1/remediation[/<id>] exactly as Api\\RemediationPresenter does (ssot/doctrine/medulla.md §5).

WHY (read set [remediation]). The security remediation queue is estate-wide and the presenter opens no face-bff
door, so a person at any tier is refused. status, severity, component and limit drop on PHP's empty() ('' and
"0"); the limit is not floored or clamped; the order is severity's CASE, then created_at DESC, ties included;
/remediation/0 lists. A negative limit is PHP's 500. Every bearer meets two URLs; wing.read meets all of them.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import pathlib
import re
import shutil
import subprocess

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
_PHP = _pre + "  $p = new App\\Presenters\\Api\\RemediationPresenter(new App\\Model\\RemediationRepository($db));\n" + _tail

#: id, finding_ref, component_id, severity, status, remediation_detail, auto_fixable, scan_cycle, created_at
ROWS = [("REM-001", "CVE-2026-0001", "traefik", "CRITICAL", "pending", "Oprava ✓", 1, 7, "2026-10-01 10:00:00"),
        ("REM-002", "CVE-2026-0002", "traefik", "HIGH", "pending", None, 0, 7, "2026-10-01 10:00:00"),
        ("REM-003", None, "grafana", "HIGH", "resolved", "", 0, None, "2026-10-01 10:00:00"),
        ("REM-004", "GHSA-x", "grafana", "MEDIUM", "wontfix", "d", 0, 0, "2026-10-02 10:00:00"),
        ("REM-005", "CVE-2026-0005", None, "LOW", "pending", "d", 1, 8, "2026-10-03 10:00:00"),
        ("REM-006", "CVE-2026-0006", "0", "LOW", "pending", "zero component", 0, 8, "2026-10-03 10:00:00"),
        ("0", "id zero", "", "MEDIUM", "pending", "the id that lists", 0, 8, "2026-10-04 10:00:00"),
        ("a b", "space id", "comp with space", "CRITICAL", "resolved", "d", 0, 9, "2026-10-05 10:00:00"),
        ("résumé", "unicode id", "traefik", "CRITICAL", "pending", "d", 0, 9, "2026-10-05 10:00:00")]
BULK = 240  # equal created_at inside each severity: the order of ties is part of the comparison
R = "/api/v1/remediation"
URLS = [R] + [f"{R}?{q}" for q in (
    "status=pending", "status=resolved", "status=wontfix", "status=0", "status=", "status=nope", "status=PENDING", "severity=HIGH",
    "severity=high", "severity=CRITICAL", "severity=0", "severity=", "component=traefik", "component=0", "component=",
    "component=comp+with+space", "component=nope", "component_id=traefik", "status=pending&severity=HIGH&component=traefik",
    "status=pending&severity=LOW", "limit=0", "limit=1", "limit=3", "limit=20", "limit=abc", "limit=3abc", "limit=", "limit=1e1",
    "limit=9999", "limit=%203", "limit=2&limit=5", "status=pending&limit=4", "status=pending&status=resolved", "id=REM-001", "sort=asc")] + [
    f"{R}/REM-001", f"{R}/REM-003", f"{R}/REM-0", f"{R}/a%20b", f"{R}/r%C3%A9sum%C3%A9", f"{R}/rem-001", f"{R}/0",
    f"{R}/0?status=resolved&limit=2", f"{R}/REM-005?status=resolved"]
EVERY_BEARER = {R, f"{R}/REM-001"}
NEGATIVE = [f"{R}?limit=-5", f"{R}?limit=-1&status=pending"]
#: The matcher keeps these away; the medulla hands them back too (404 at its door).
HANDED_BACK = [f"{R}/next-id", f"{R}/bulk-status", f"{R}/", f"{R}/a/b", f"{R}x", f"{R}/REM-001/x", "/remediation"]


def _seed_remediation(db: pathlib.Path) -> None:
    q = lambda v: "NULL" if v is None else (str(v) if isinstance(v, int) else "'" + str(v).replace("'", "''") + "'")  # noqa: E731
    sql = ["DELETE FROM remediation_items;"]
    sql += [f"INSERT INTO remediation_items (id, finding_ref, component_id, severity, status, remediation_detail, auto_fixable, "
            f"scan_cycle, created_at) VALUES ({', '.join(q(v) for v in r)});" for r in ROWS]
    sql.append(f"WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < {BULK}) INSERT INTO remediation_items "
               "(id, component_id, severity, status, created_at) SELECT 'BULK-' || printf('%04d', (i * 7919) % 1000 * 10 + i % 10), "
               "CASE i % 3 WHEN 0 THEN 'traefik' WHEN 1 THEN 'grafana' ELSE NULL END, "
               "CASE i % 4 WHEN 0 THEN 'CRITICAL' WHEN 1 THEN 'HIGH' WHEN 2 THEN 'MEDIUM' ELSE 'LOW' END, "
               "CASE i % 5 WHEN 0 THEN 'resolved' WHEN 1 THEN 'wontfix' ELSE 'pending' END, '2026-09-0' || (1 + i % 2) || ' 00:00:00' FROM n;")
    subprocess.run(["sqlite3", str(db)], input="\n".join(sql), text=True, check=True)


def test_the_caddyfile_moves_only_the_remediation_gets():
    block = re.search(r"@medulla_read_remediation \{(.*?)\n    \}", p._render(["remediation"]), re.S).group(1).split()
    assert block == ["method", "GET", "path_regexp", "^/api/v1/remediation(/[^/]+)?$", "not", "path", f"{R}/bulk-status",
                     "not", "path", f"{R}/next-id"], block
    rx = re.compile(block[3])
    for path in (R, f"{R}/REM-001", f"{R}/0"):
        assert rx.search(path), path
    for path in HANDED_BACK[2:]:
        assert not rx.search(path), path
    assert "@medulla_read_remediation" not in p._render(["security", "agent-sessions"])


@m.needs_cargo
@pytest.mark.skipif(not shutil.which("php"), reason="php runs Wing")
@pytest.mark.skipif(not m.AUTOLOAD.exists(), reason="wing vendor/autoload.php missing (composer install)")
@pytest.mark.skipif(not shutil.which("sqlite3"), reason="sqlite3 seeds the scratch wing.db")
def test_php_and_the_medulla_answer_every_remediation_read_the_same(tmp_path, monkeypatch):
    monkeypatch.setenv("NOS_HALT_FILE", str(tmp_path / "halt"))
    subprocess.run(["php", str(m.WING / "bin/init-db.php"), f"--data-dir={tmp_path}"], capture_output=True, check=True, timeout=60)
    db = tmp_path / "wing.db"
    p._seed(db)
    _seed_remediation(db)
    cases = [{"url": u, "headers": h, "auth": a} for u in URLS for a, h in p.AUTH.items() if u in EVERY_BEARER or a == "wing.read"]
    neg = [{"url": u, "headers": p.AUTH["wing.read"], "auth": "wing.read"} for u in NEGATIVE]
    exe = m._medulla(tmp_path)
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    proc, port = m._serve(exe, db)
    try:
        got = [p._medulla_get(port, c["url"], c["headers"]) for c in cases + neg]
        handed_back = [p._medulla_get(port, u, p.AUTH["wing.read"])[0] for u in HANDED_BACK]
    finally:
        proc.kill()
        proc.wait()
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before, "a medulla read changed wing.db"
    assert handed_back == [404] * len(HANDED_BACK), f"the medulla answered a path PHP keeps: {handed_back}"
    r = subprocess.run(["php", "-d", "error_reporting=E_ALL", "-r", _PHP, str(m.AUTOLOAD), str(db), json.dumps(cases + neg)],
                       capture_output=True, text=True, timeout=300, check=False, cwd=m.WING)
    assert r.returncode == 0, (r.stdout + r.stderr)[-4000:]
    php = json.loads(r.stdout)
    for want, (code, _, body) in zip(php[len(cases):], got[len(cases):]):
        assert (want["code"], code) == (500, 500) and "Negative offset or limit" in want["body"] + body, (want, code, body)
    php, got = php[:len(cases)], got[:len(cases)]
    paths = m.yaml.safe_load(m.OPENAPI.read_text(encoding="utf-8"))["paths"]
    codes: dict[str, set[int]] = {}
    for c, want, (code, ctype, body) in zip(cases, php, got):
        where = f"{c['url']} as {c['auth']}"
        op = paths[R if c["url"].split("?")[0] == R else R + "/{id}"]
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
    everything = seen(R)
    assert len(everything["items"]) == 100 and everything["total"] == len(ROWS) + BULK, everything["total"]
    rank = {"CRITICAL": 1, "HIGH": 2, "MEDIUM": 3, "LOW": 4}
    order = [(rank[i["severity"]], i["created_at"]) for i in seen(f"{R}?limit=9999")["items"]]
    assert len(order) == everything["total"], len(order)
    assert all(a[0] < b[0] or (a[0] == b[0] and a[1] >= b[1]) for a, b in zip(order, order[1:])), "severity, then newest first"
    assert len(seen(f"{R}?limit=0")["items"]) == 100 and seen(f"{R}?limit=abc")["items"] == [], "limit=0 is the default, abc is (int) 0"
    assert seen(f"{R}?component=0")["total"] == everything["total"] and seen(f"{R}?status=PENDING")["total"] == 0
    assert seen(f"{R}/0")["total"] == everything["total"], "/remediation/0 lists, as PHP's truth test does"
    assert seen(f"{R}/a%20b")["id"] == "a b" and seen(f"{R}/REM-005?status=resolved")["id"] == "REM-005"
