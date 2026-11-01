"""The medulla answers GET /api/v1/inbox/questions[/<uuid>] exactly as Api\\InboxPresenter does (ssot/doctrine/medulla.md §5).

WHY (read set [inbox]). An agent blocked on the operator is the most time-sensitive thing he can see, and
reading it writes nothing: listOpen and poll move, answer and cancel stay PHP's (the Caddy matcher is GET
only). PHP's deadline rule is a string compare against gmdate('Y-m-d\\TH:i:s\\Z'); the medulla makes the
same compare for that one stored form and says 503 for any other, never a guess. Parity is measured as for
the Pulse reads: the real presenter and the medulla answer one scratch wing.db x every bearer.
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
_PHP = (_pre + "  $p = new App\\Presenters\\Api\\InboxPresenter(new App\\Model\\AgentQuestionRepository($db,\n"
        + "    new App\\Model\\EventRepository($db), new App\\Model\\NotificationRepository($db)));\n"
        + _rest[_rest.index("  $p->tokenRepo"):])

PAST, FUTURE = "2001-01-01T00:00:00Z", "2999-01-01T00:00:00Z"  # far from now: no clock to freeze
#: uuid -> (agent, status, expires_at, answer, created_at)
QUESTIONS = {"q-open": ("alpha", "open", None, None, "2026-10-01 10:00:00"),
             "q-open-later": ("beta", "open", FUTURE, None, "2026-10-01 11:00:00"),
             "q-past": ("alpha", "open", PAST, None, "2026-10-01 09:00:00"),
             "q-blank": ("beta", "open", "", None, "2026-10-01 12:00:00"),
             "q-answered": ("alpha", "answered", FUTURE, "yes", "2026-10-01 08:00:00"),
             "q-cancelled": ("beta", "cancelled", None, "not needed", "2026-10-01 07:00:00"),
             "q-expired": ("alpha", "expired", PAST, "no", "2026-10-01 06:00:00")}
URLS = ["/api/v1/inbox/questions", "/api/v1/inbox/questions?agent=alpha", "/api/v1/inbox/questions?agent=beta",
        "/api/v1/inbox/questions?agent=", "/api/v1/inbox/questions?agent=nobody", "/api/v1/inbox/questions/nope"]
URLS += [f"/api/v1/inbox/questions/{u}" for u in QUESTIONS]


def _seed_questions(db: pathlib.Path, rows: dict) -> None:
    q = lambda v: "NULL" if v is None else "'" + str(v).replace("'", "''") + "'"  # noqa: E731
    sql = [f"INSERT INTO agent_questions (uuid, agent_name, kind, prompt, context_json, reply_token_sha, status, answer, "
           f"expires_at, default_on_expiry, actor_id, created_at, updated_at) VALUES ({q(u)}, {q(a)}, 'approval', "
           f"'Smazat {u}? ✓ a/b', '{{\"step\": 3}}', {q(hashlib.sha256(u.encode()).hexdigest())}, {q(s)}, {q(ans)}, "
           f"{q(exp)}, 'deny', 'agent:{a}', {q(at)}, {q(at)});" for u, (a, s, exp, ans, at) in rows.items()]
    subprocess.run(["sqlite3", str(db)], input="\n".join(sql), text=True, check=True)


def _matcher() -> list[str]:
    return re.search(r"@medulla_read_inbox \{(.*?)\n    \}", p._render(["inbox"]), re.S).group(1).split()


def test_the_caddyfile_moves_only_the_inbox_gets():
    block = _matcher()
    assert block[:3] == ["method", "GET", "path_regexp"] and len(block) == 4, block
    rx = re.compile(block[3])
    for path in ("/api/v1/inbox/questions", "/api/v1/inbox/questions/q-1"):
        assert rx.search(path), path
    # answer and cancel are writes: POST, and a path this matcher does not take even as a GET.
    for path in ("/api/v1/inbox/questions/q-1/answer", "/api/v1/inbox/questions/q-1/cancel", "/api/v1/inbox/questions/"):
        assert not rx.search(path), path
    assert "@medulla_read_inbox" not in p._render(["pulse", "audit"])


def _medulla_answers(exe, db, cases):
    proc, port = m._serve(exe, db)
    try:
        return [p._medulla_get(port, c["url"], c["headers"]) for c in cases]
    finally:
        proc.kill()
        proc.wait()


@m.needs_cargo
@pytest.mark.skipif(not shutil.which("php"), reason="php runs Wing")
@pytest.mark.skipif(not m.AUTOLOAD.exists(), reason="wing vendor/autoload.php missing (composer install)")
@pytest.mark.skipif(not shutil.which("sqlite3"), reason="sqlite3 seeds the scratch wing.db")
def test_php_and_the_medulla_answer_every_inbox_read_the_same(tmp_path, monkeypatch):
    monkeypatch.setenv("NOS_HALT_FILE", str(tmp_path / "halt"))
    subprocess.run(["php", str(m.WING / "bin/init-db.php"), f"--data-dir={tmp_path}"], capture_output=True, check=True, timeout=60)
    db = tmp_path / "wing.db"
    p._seed(db)
    _seed_questions(db, QUESTIONS)
    cases = [{"url": u, "headers": h, "auth": a} for u in URLS for a, h in p.AUTH.items()]
    exe = m._medulla(tmp_path)
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    got = _medulla_answers(exe, db, cases)
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before, "a medulla read changed wing.db"
    r = subprocess.run(["php", "-d", "error_reporting=E_ALL", "-r", _PHP, str(m.AUTOLOAD), str(db), json.dumps(cases)],
                       capture_output=True, text=True, timeout=300, check=False, cwd=m.WING)
    assert r.returncode == 0, (r.stdout + r.stderr)[-4000:]
    php = json.loads(r.stdout)
    paths = m.yaml.safe_load(m.OPENAPI.read_text(encoding="utf-8"))["paths"]
    codes: set[int] = set()
    for c, want, (code, ctype, body) in zip(cases, php, got):
        where = f"{c['url']} as {c['auth']}"
        op = paths["/api/v1/inbox/questions" if c["url"].count("/") == 4 else "/api/v1/inbox/questions/{uuid}"]
        assert str(code) in op["get"]["responses"], f"{where}: {code} is not in wing.openapi.yml"
        assert (code, ctype) == (want["code"], "application/json; charset=utf-8"), f"{where}: medulla {code} {ctype} {body[:300]} / php {want}"
        assert json.loads(body) == json.loads(want["body"]), f"{where}:\nmedulla {body[:1500]}\nphp     {want['body'][:1500]}"
        assert "reply_token_sha" not in body, where
        codes.add(code)
    # The seed reaches every outcome; a fixture gone blind would pass the comparison vacuously.
    assert codes == {200, 401, 403, 404}, codes
    read = list(p.AUTH).index("wing.read")
    seen = lambda url: json.loads(got[URLS.index(url) * len(p.AUTH) + read][2])  # noqa: E731
    assert [q["uuid"] for q in seen("/api/v1/inbox/questions")["questions"]] == ["q-open", "q-open-later", "q-blank"]
    assert [q["uuid"] for q in seen("/api/v1/inbox/questions?agent=alpha")["questions"]] == ["q-open"]
    past = seen("/api/v1/inbox/questions/q-past")
    assert (past["status"], past["answer"], past.get("expired_by_deadline")) == ("expired", "deny", True), past


@m.needs_cargo
@pytest.mark.skipif(not shutil.which("php"), reason="php builds the schema")
@pytest.mark.skipif(not shutil.which("sqlite3"), reason="sqlite3 seeds the scratch wing.db")
def test_a_deadline_in_another_form_is_unknown_not_guessed(tmp_path, monkeypatch):
    # PHP compares any string lexically; the medulla vouches only for the form ask() writes.
    monkeypatch.setenv("NOS_HALT_FILE", str(tmp_path / "halt"))
    subprocess.run(["php", str(m.WING / "bin/init-db.php"), f"--data-dir={tmp_path}"], capture_output=True, check=True, timeout=60)
    db = tmp_path / "wing.db"
    p._seed(db)
    _seed_questions(db, {"q-odd": ("alpha", "open", "2001-01-01 00:00:00", None, "2026-10-01 10:00:00")})
    auth = p.AUTH["wing.read"]
    cases = [{"url": u, "headers": auth} for u in ("/api/v1/inbox/questions", "/api/v1/inbox/questions/q-odd")]
    for code, _, body in _medulla_answers(m._medulla(tmp_path), db, cases):
        assert code == 503 and "UNKNOWN" in json.loads(body)["error"], (code, body)
