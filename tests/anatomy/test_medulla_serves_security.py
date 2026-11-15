"""The medulla answers GET /api/v1/advisories[/<id>] and /gitleaks_findings[/<id>] as PHP does (ssot/doctrine/medulla.md §5).

WHY (read set [security]). Advisories and leaked-secret findings are estate-wide and neither presenter opens a
face-bff door, so a person at any tier is refused. The advisory list never carries full_text; array_filter drops
'' and "0" there and the limit is not clamped. Findings filter on "0", clamp to 1..500, leave as an object keyed
by id. A negative advisory limit is PHP's 500. Every bearer meets four URLs (auth runs first); wing.read meets all.
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
_PHP = (_pre + "  $p = $name === 'Api:Advisories' ? new App\\Presenters\\Api\\AdvisoriesPresenter(new App\\Model\\AdvisoryRepository($db))\n"
        + "    : new App\\Presenters\\Api\\GitleaksPresenter(new App\\Model\\GitleaksRepository($db));\n" + _tail)

#: filename, title, date, has_critical, has_pentest, full_text, scan_cycle, created_at
ADV = [("2026-10-01-a.md", "První ✓", "2026-10-01", 1, 0, "FULL-TEXT-MARK critical ✓", 7, "2026-10-01 08:00:00"),
       ("2026-10-01-b.md", None, "2026-10-01", 0, 1, "FULL-TEXT-MARK pentest", None, "2026-10-01 09:00:00"),
       ("2026-10-02.md", "Second", "2026-10-02", 0, 0, "FULL-TEXT-MARK x", 0, "2026-10-02 08:00:00"),
       ("zero.md", "0", "0", 0, 0, "FULL-TEXT-MARK 0", 1, "2026-10-03 08:00:00"),
       ("2026-09-30.md", "", "2026-09-30", 1, 1, "FULL-TEXT-MARK y", 3, "2026-09-30 08:00:00")]
ADV_BULK = 30  # more than the list's default 20
#: id, fingerprint, rule_id, description, secret_masked, file_path, line_start, commit_sha, author, date, severity,
#: repo_path, scan_id, resolved_at, resolved_by, created_at
GL = [("f-1", "fp1", "generic-api-key", "Klíč ✓", "abcd…wxyz", "a/b.py", 3, "c0ffee", "a <a@example.invalid>", "2026-10-01T10:00:00Z",
       "high", "/repo", "s-1", None, None, "2026-10-05 10:00:00"),
      ("f-2", "fp2", "aws-access-token", None, "AKIA…1234", "x.env", 1, None, None, None, "critical", "/repo", "s-1",
       "2026-10-06T00:00:00+00:00", "operator", "2026-10-05 10:00:00"),
      ("f-3", "fp3", "generic-api-key", "", None, "c.txt", 0, None, None, None, "HIGH", "/repo2", None, None, None, "2026-10-05 10:00:00"),
      ("f 4", "fp4", "0", "zero rule", "0", "0", 0, "0", "0", "0", "0", "0", "0", None, None, "2026-10-04 10:00:00"),
      ("f-5", "fp5", "rule with space", "d", "m", "p", 9, None, None, None, "low", "/repo", "s-2", "", "", "2026-10-07 10:00:00"),
      ("résumé", "fp6", "generic-api-key", "d", "m", "p", 9, None, None, None, "info", "/repo", "s-2", None, None, "2026-10-03 10:00:00")]
GL_BULK = 520  # more than the 500 ceiling
A, G = "/api/v1/advisories", "/api/v1/gitleaks_findings"
URLS = [A] + [f"{A}?{q}" for q in (
    "date=2026-10-01", "date=0", "date=", "date=nope", "date=2026-10-01&limit=1", "limit=0", "limit=1", "limit=3", "limit=abc",
    "limit=3abc", "limit=", "limit=1e1", "limit=9999", "limit=%203", "limit=2&limit=4", "date=2026-10-02&date=2026-10-01", "since=x")] + [
    f"{A}/1", f"{A}/2", f"{A}/4", f"{A}/999999", f"{A}/3?date=x&limit=1", f"{A}/123456789012345678", G] + [f"{G}?{q}" for q in (
        "rule_id=generic-api-key", "rule_id=0", "rule_id=", "rule_id=nope", "rule_id=rule+with+space", "severity=high", "severity=HIGH",
        "severity=0", "severity=", "scan_id=s-1", "scan_id=0", "scan_id=", "scan_id=s-2&severity=low", "open_only=1", "open_only=0",
        "open_only=", "open_only=true", "open_only=1&rule_id=generic-api-key", "limit=0", "limit=1", "limit=2", "limit=501", "limit=abc",
        "limit=-5", "limit=", "limit=3abc", "rule_id=generic-api-key&rule_id=0", "resolved=1")] + [
    f"{G}/f-1", f"{G}/f-2", f"{G}/does-not-exist", f"{G}/f%204", f"{G}/r%C3%A9sum%C3%A9", f"{G}/resolve", f"{G}/f-5?open_only=1", f"{G}/0"]
EVERY_BEARER = {A, f"{A}/1", G, f"{G}/f-1"}  # each presenter's list and one row
NEGATIVE = [f"{A}?limit=-5", f"{A}?limit=-1&date=2026-10-01"]
#: The matcher keeps these away; the medulla hands them back too (404 at its door).
HANDED_BACK = [f"{A}/0", f"{A}/abc", f"{A}/007", f"{A}/-1", f"{A}/1/x", f"{A}/", f"{A}x", f"{A}/1234567890123456789",
               f"{G}/f-1/resolve", f"{G}/", f"{G}/a/b", "/api/v1/pentest"]


def _seed_security(db: pathlib.Path) -> None:
    q = lambda v: "NULL" if v is None else (str(v) if isinstance(v, int) else "'" + str(v).replace("'", "''") + "'")  # noqa: E731
    sql = ["DELETE FROM advisories;", "DELETE FROM gitleaks_findings;"]
    sql += [f"INSERT INTO advisories (filename, title, date, has_critical, has_pentest, full_text, scan_cycle, created_at) "
            f"VALUES ({', '.join(q(v) for v in r)});" for r in ADV]
    sql.append(f"WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < {ADV_BULK}) INSERT INTO advisories "
               "(filename, date, full_text) SELECT 'bulk-' || i || '.md', '2026-08-' || printf('%02d', 1 + i % 5), 'FULL-TEXT-MARK bulk' FROM n;")
    sql += [f"INSERT INTO gitleaks_findings (id, fingerprint, rule_id, description, secret_masked, file_path, line_start, commit_sha, "
            f"author, date, severity, repo_path, scan_id, resolved_at, resolved_by, created_at) VALUES ({', '.join(q(v) for v in r)});" for r in GL]
    sql.append(f"WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < {GL_BULK}) INSERT INTO gitleaks_findings "
               "(id, fingerprint, rule_id, file_path, line_start, repo_path, scan_id, created_at) SELECT 'bulk-' || i, 'bfp-' || i, "
               "'bulk', 'f', i, '/r', 'bulk', '2026-09-0' || (1 + i % 3) || ' 00:00:00' FROM n;")
    subprocess.run(["sqlite3", str(db)], input="\n".join(sql), text=True, check=True)


def test_the_caddyfile_moves_only_the_security_gets():
    block = re.search(r"@medulla_read_security \{(.*?)\n    \}", p._render(["security"]), re.S).group(1).split()
    assert block[:3] == ["method", "GET", "path_regexp"] and block[4:] == ["not", "path_regexp", "/resolve$"], block
    rx, resolve = re.compile(block[3]), re.compile(block[6])
    moves = lambda path: bool(rx.search(path)) and not resolve.search(path)  # noqa: E731
    for path in (A, f"{A}/12", f"{A}/123456789012345678", G, f"{G}/3f2a-uuid", f"{G}/f%204"):
        assert moves(path), path
    for path in (*HANDED_BACK, f"{A}/resolve", f"{G}/resolve", f"{G}x"):
        assert not moves(path), path
    assert "@medulla_read_security" not in p._render(["hub", "events"])


@m.needs_cargo
@pytest.mark.skipif(not shutil.which("php"), reason="php runs Wing")
@pytest.mark.skipif(not m.AUTOLOAD.exists(), reason="wing vendor/autoload.php missing (composer install)")
@pytest.mark.skipif(not shutil.which("sqlite3"), reason="sqlite3 seeds the scratch wing.db")
def test_php_and_the_medulla_answer_every_security_read_the_same(tmp_path, monkeypatch):
    monkeypatch.setenv("NOS_HALT_FILE", str(tmp_path / "halt"))
    subprocess.run(["php", str(m.WING / "bin/init-db.php"), f"--data-dir={tmp_path}"], capture_output=True, check=True, timeout=60)
    db = tmp_path / "wing.db"
    p._seed(db)
    _seed_security(db)
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
        base = c["url"].split("?")[0]
        op = paths[base if base in (A, G) else (A if base.startswith(A) else G) + "/{id}"]
        assert str(code) in op["get"]["responses"], f"{where}: {code} is not in wing.openapi.yml"
        assert (code, ctype) == (want["code"], "application/json; charset=utf-8"), f"{where}: medulla {code} {ctype} {body[:300]} / php {want}"
        assert p._comparable(body) == p._comparable(want["body"]), f"{where}:\nmedulla {body[:1500]}\nphp     {want['body'][:1500]}"
        codes.setdefault(c["auth"], set()).add(code)
    # The seed reaches every outcome; a fixture gone blind would pass the comparison vacuously.
    assert set().union(*codes.values()) == {200, 401, 403, 404}, codes
    assert (codes["face-bff, tier 1"], codes["face-bff, tier 3"], codes["thalamus, a person"]) == ({403}, {403}, {403}), codes
    p._intents_refused(cases, got)
    read = [i for i, c in enumerate(cases) if c["auth"] == "wing.read"]
    seen = lambda url: json.loads(got[read[URLS.index(url)]][2])  # noqa: E731
    lists = [json.dumps(seen(u)) for u in URLS if u.split("?")[0] == A]
    assert not any("FULL-TEXT-MARK" in t or "full_text" in t for t in lists), "an advisory list carries full_text"
    assert "FULL-TEXT-MARK" in seen(f"{A}/1")["full_text"]
    assert seen(A)["total"] == 20 == len(seen(f"{A}?limit=0")["advisories"]) and seen(f"{A}?limit=abc") == {"advisories": [], "total": 0}
    assert len(seen(f"{A}?limit=9999")["advisories"]) == len(ADV) + ADV_BULK and seen(f"{A}?date=0")["total"] == 20, "limit unclamped, date=0 dropped"
    assert [a["filename"] for a in seen(f"{A}?date=2026-10-01")["advisories"]] == ["2026-10-01-b.md", "2026-10-01-a.md"], "date DESC, id DESC"
    assert len(seen(G)["findings"]) == 200 and len(seen(f"{G}?limit=501")["findings"]) == 500 and len(seen(f"{G}?limit=abc")["findings"]) == 1
    assert list(seen(f"{G}?rule_id=0")["findings"]) == ["f 4"] == list(seen(f"{G}?scan_id=0")["findings"]), "a findings filter of 0 filters"
    assert set(seen(f"{G}?open_only=1&rule_id=generic-api-key")["findings"]) == {"f-1", "f-3", "résumé"} and seen(f"{G}?rule_id=nope")["findings"] == []
