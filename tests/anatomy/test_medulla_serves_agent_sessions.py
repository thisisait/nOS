"""The medulla answers GET /api/v1/agents/<name>/sessions exactly as Api\\AgentsPresenter does (ssot/doctrine/medulla.md §5).

WHY (read set [agent-sessions]). A token and a Tier-1 person read every session of an agent; a face-bff person
below Tier 1 reads only rows whose actor_id is user:<their uid>. Reading another person's session is the leak
this read could cause, so the scope comes from the bearer, uid and groups alone, never a query parameter. Newest
100 by id. The POST that starts a session, the detail and the catalogue stay PHP's. Every URL x every bearer.
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
# actionSessions reads $sessions alone: the loader and OperatorTrigger (the POST's spawn) are never built.
_PHP = (_pre + "  $rc = new ReflectionClass(App\\Presenters\\Api\\AgentsPresenter::class);\n  $p = $rc->newInstanceWithoutConstructor();\n"
        + "  $rc->getProperty('sessions')->setValue($p, new App\\Model\\AgentSessionRepository($db));\n"
        + "  (new ReflectionMethod(Nette\\Application\\UI\\Presenter::class, '__construct'))->invoke($p);\n"
        + _rest[_rest.index("  $p->tokenRepo"):])

#: agent_name, actor_id, status. Near-miss actors (user:alice-2, USER:ALICE, alice) are not alice's rows.
ROWS = [("conductor", "user:alice", "idle"), ("conductor", "user:bob", "running"), ("conductor", "agent:conductor", "terminated"),
        ("conductor", "operator", "idle"), ("conductor", "user:alice-2", "idle"), ("conductor", "USER:ALICE", "idle"),
        ("conductor", "alice", "idle"), ("librarian", "user:alice", "idle"), ("librarian", "user:bob", "idle"),
        ("a b", "user:alice", "idle"), ("0", "user:bob", "idle")]
BULK = 130  # conductor rows, bob's and the conductor's by turns, so LIMIT 100 cuts
AUTH = {**p.AUTH,
        "face-bff, tier 3 bob": {"Authorization": "Bearer bff", "X-Nos-User-Uid": "bob", "X-Nos-User-Groups": "nos-users"},
        "face-bff, tier 3 carol": {"Authorization": "Bearer bff", "X-Nos-User-Uid": "carol", "X-Nos-User-Groups": ""},
        "face-bff, tier 1 bob": {"Authorization": "Bearer bff", "X-Nos-User-Uid": "bob", "X-Nos-User-Groups": "nos-users, nos-providers"},
        "face-bff, near-miss group": {"Authorization": "Bearer bff", "X-Nos-User-Uid": "alice", "X-Nos-User-Groups": "nos-admins-x|xnos-admins"},
        "face-bff, uid with colon": {"Authorization": "Bearer bff", "X-Nos-User-Uid": "user:bob", "X-Nos-User-Groups": "nos-users"}}
S = "/api/v1/agents/{}/sessions"
C = S.format("conductor")
URLS = [C, S.format("librarian"), S.format("nope"), S.format("a%20b"), S.format("0"), S.format("Conductor")]
FORGED = [C + "?actor_id=user:bob", C + "?scope=&limit=1&name=librarian", C + "?uid=bob&actor=user%3Abob"]
URLS += FORGED
HANDED_BACK = ["/api/v1/agents", "/api/v1/agents/conductor", C + "/x", "/api/v1/agents//sessions", "/api/v1/agents/a/b/sessions",
               "/api/v1/agent-sessions/00000000-0000-4000-8000-000000000000", C + "x"]


def _seed_sessions(db: pathlib.Path) -> None:
    q = lambda v: "NULL" if v is None else "'" + str(v).replace("'", "''") + "'"  # noqa: E731
    ins = ("INSERT INTO agent_sessions (uuid, agent_name, agent_version, status, trigger, actor_id, trace_id, model_uri, started_at, "
           "result_json) VALUES ")
    sql = ["DELETE FROM agent_sessions;"]
    sql += [ins + f"({q(f'u-{i}')}, {q(a)}, 1, {q(st)}, 'operator', {q(actor)}, 't', 'm', '2026-10-01T10:00:00Z', "
            f"{q(json.dumps({'msg': 'Výsledek ✓ ' + actor}))});" for i, (a, actor, st) in enumerate(ROWS)]
    sql.append(f"WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < {BULK}) " + ins.replace(" VALUES ", " ")
               + "SELECT 'bulk-' || i, 'conductor', 1, 'idle', 'pulse', CASE WHEN i % 2 THEN 'user:bob' ELSE 'agent:conductor' END, "
               "'t', 'm', '2026-10-02T10:00:00Z', NULL FROM n;")
    subprocess.run(["sqlite3", str(db)], input="\n".join(sql), text=True, check=True)


def test_the_caddyfile_moves_only_the_sessions_get():
    block = re.search(r"@medulla_read_agent-sessions \{(.*?)\n    \}", p._render(["agent-sessions"]), re.S).group(1).split()
    assert block == ["method", "GET", "path_regexp", "^/api/v1/agents/[^/]+/sessions$"], block
    rx = re.compile(block[3])
    assert rx.search(C) and rx.search(S.format("a%20b")), block
    for path in HANDED_BACK:
        assert not rx.search(path), path
    assert "@medulla_read_agent-sessions" not in p._render(["security", "events"])


@m.needs_cargo
@pytest.mark.skipif(not shutil.which("php"), reason="php runs Wing")
@pytest.mark.skipif(not m.AUTOLOAD.exists(), reason="wing vendor/autoload.php missing (composer install)")
@pytest.mark.skipif(not shutil.which("sqlite3"), reason="sqlite3 seeds the scratch wing.db")
def test_php_and_the_medulla_answer_every_sessions_read_the_same(tmp_path, monkeypatch):
    monkeypatch.setenv("NOS_HALT_FILE", str(tmp_path / "halt"))
    subprocess.run(["php", str(m.WING / "bin/init-db.php"), f"--data-dir={tmp_path}"], capture_output=True, check=True, timeout=60)
    db = tmp_path / "wing.db"
    p._seed(db)
    _seed_sessions(db)
    cases = [{"url": u, "headers": h, "auth": a} for u in URLS for a, h in AUTH.items()]
    exe = m._medulla(tmp_path)
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    proc, port = m._serve(exe, db)
    try:
        got = [p._medulla_get(port, c["url"], c["headers"]) for c in cases]
        handed_back = [p._medulla_get(port, u, AUTH["wing.read"])[0] for u in HANDED_BACK]
    finally:
        proc.kill()
        proc.wait()
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before, "a medulla read changed wing.db"
    assert handed_back == [404] * len(HANDED_BACK), f"the medulla answered a path PHP keeps: {handed_back}"
    r = subprocess.run(["php", "-d", "error_reporting=E_ALL", "-r", _PHP, str(m.AUTOLOAD), str(db), json.dumps(cases)],
                       capture_output=True, text=True, timeout=300, check=False, cwd=m.WING)
    assert r.returncode == 0, (r.stdout + r.stderr)[-4000:]
    php = json.loads(r.stdout)
    op = m.yaml.safe_load(m.OPENAPI.read_text(encoding="utf-8"))["paths"]["/api/v1/agents/{name}/sessions"]["get"]
    codes: dict[str, set[int]] = {}
    for c, want, (code, ctype, body) in zip(cases, php, got):
        where = f"{c['url']} as {c['auth']}"
        assert str(code) in op["responses"], f"{where}: {code} is not in wing.openapi.yml"
        assert (code, ctype) == (want["code"], "application/json; charset=utf-8"), f"{where}: medulla {code} {ctype} {body[:300]} / php {want}"
        assert json.loads(body) == json.loads(want["body"]), f"{where}:\nmedulla {body[:1500]}\nphp     {want['body'][:1500]}"
        codes.setdefault(c["auth"], set()).add(code)
    # The seed reaches every outcome; a fixture gone blind would pass the comparison vacuously.
    assert set().union(*codes.values()) == {200, 401, 403}, codes
    assert (codes["face-bff, tier 3"], codes["thalamus, a person"], codes["face-bff, uid with colon"]) == ({200}, {403}, {401}), codes
    p._intents_refused(cases, got)
    seen = lambda url, who: json.loads(got[URLS.index(url) * len(AUTH) + list(AUTH).index(who)][2])  # noqa: E731
    actors = lambda url, who: {r["actor_id"] for r in seen(url, who)["data"]}  # noqa: E731
    for who in ("wing.read", "face-bff, tier 1", "face-bff, tier 1 bob"):
        rows = seen(C, who)["data"]
        assert len(rows) == 100 and len(actors(C, who)) > 1 and [r["id"] for r in rows] == sorted((r["id"] for r in rows), reverse=True), who
    # Own rows only: alice never sees bob's session, nor a near-miss actor; bob never sees alice's.
    assert actors(C, "face-bff, tier 3") == {"user:alice"} and seen(C, "face-bff, tier 3")["total"] == 1
    assert actors(C, "face-bff, tier 3 bob") == {"user:bob"} and seen(C, "face-bff, tier 3 bob")["total"] == 66
    assert seen(C, "face-bff, tier 3 carol") == {"data": [], "total": 0}
    assert actors(C, "face-bff, near-miss group") == {"user:alice"}, "a near-miss group name widened the read"
    for url in FORGED:
        assert actors(url, "face-bff, tier 3") == {"user:alice"}, f"a query parameter widened the read: {url}"
    assert actors(S.format("librarian"), "face-bff, tier 3") == {"user:alice"} and seen(S.format("0"), "face-bff, tier 3")["total"] == 0
