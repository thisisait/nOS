"""The medulla answers GET /api/v1/events exactly as Api\\EventsPresenter does (ssot/doctrine/medulla.md §5).

WHY (read set [events]). The event spine is estate-wide: a token reads it, a face-bff person only at Tier 1,
so a Tier-3 person or a thalamus person reading it is a leak. The callback's HMAC POST stays PHP's. Nine
filters drop on PHP's empty() ('' and "0"), limit clamps to 1..500, result_json decodes as json_decode.
Every bearer meets two URLs (auth runs before the query); every URL meets an allowed token, a Tier-1 and a Tier-3 person.
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
_PHP = (_pre + "  $p = new App\\Presenters\\Api\\EventsPresenter(new App\\Model\\EventRepository($db), "
        + "new App\\Model\\AgentSessionRepository($db));\n" + _rest[_rest.index("  $p->tokenRepo"):])

#: (ts, run_id, type, result_json, migration_id, upgrade_id, coexist_svc, source, actor_id, actor_action_id, duration_ms, changed)
ROWS = [
    ("2026-10-01T10:00:00Z", "run-a", "task_ok", '{"msg":"Záloha ✓","rc":0}', None, None, None, "callback", None, None, 12, 1),
    ("2026-10-02T10:00:00Z", "run-a", "task_failed", "not json", "m-1", None, None, "callback", None, None, None, 0),
    ("2026-10-03T10:00:00Z", "run-b", "agent_run_start", None, None, "u-1", None, "agent:x", "conductor", "aa-1", None, None),
    ("2026-10-04T10:00:00Z", "run-b", "agent_run_end", "", None, "u-1", None, "agent:x", "conductor", "aa-1", 900, None),
    ("2026-10-05T10:00:00Z", "0", "task_ok", "0", "0", "0", "0", "0", "0", "0", 0, 0),
    ("2026-10-06T10:00:00Z", "run-c", "task_ok", "{}", None, None, "grafana", "operator", None, None, None, None),
    ("2026-10-07T10:00:00Z", "run-c", "task_ok", "[]", None, None, "grafana", "operator", None, None, None, None),
    ("2026-10-08T10:00:00Z", "run-c", "task_ok", '"str"', None, None, None, None, None, None, None, None),
    ("2026-10-09T10:00:00Z", "run-c", "task_ok", "null", None, None, None, None, None, None, None, None),
    ("2026-10-10T10:00:00Z", "run-c", "task_ok", '{"0":"a","1":"b"}', None, None, None, None, None, None, None, None),
    ("2026-10-11T10:00:00Z", "run-c", "task_ok", '{"1":"b","0":"a","n":12345678901234567890,"d":{"k":1,"k":2},"e":[{}]}',
     None, None, None, None, None, None, None, None),
    ("2026-10-12 10:00:00", "run d", "type with space", " [1, 2] ", None, None, None, None, "agent:é", None, None, None),
]
BULK = 520  # more than limit's 500 ceiling

URLS = ["/api/v1/events"] + [f"/api/v1/events?{q}" for q in (
    "run_id=run-a", "run_id=0", "run_id=", "run_id=nope", "run_id=run%20d", "type=type+with+space",
    "since=2026-10", "since=2026-10-06T10:00:00Z", "since=0", "migration_id=m-1", "upgrade_id=u-1", "coexist_svc=grafana",
    "source=agent%3Ax", "source=0", "actor_id=conductor", "actor_id=agent:%C3%A9", "actor_action_id=aa-1", "patch_id=x",
    "limit=0", "limit=1", "limit=9999", "limit=abc", "limit=3abc", "limit=-5", "limit=1e1&limit=7",
    "type=task_ok&run_id=run-c&since=2026-10-08&limit=2", "run_id=run-a&run_id=run-b")]
EVERY_BEARER = {"/api/v1/events", "/api/v1/events?run_id=run-a"}
READERS = {"wing.read", "face-bff, tier 1", "face-bff, tier 3"}


def _seed_events(db: pathlib.Path) -> None:
    q = lambda v: "NULL" if v is None else (str(v) if isinstance(v, int) else "'" + str(v).replace("'", "''") + "'")  # noqa: E731
    sql = [f"INSERT INTO events (ts, run_id, type, task, result_json, migration_id, upgrade_id, coexist_svc, source, actor_id, "
           f"actor_action_id, duration_ms, changed) VALUES ({q(r[0])}, {q(r[1])}, {q(r[2])}, 'Úloha ✓', "
           f"{', '.join(q(v) for v in r[3:])});" for r in ROWS]
    sql.append(f"WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < {BULK}) "
               "INSERT INTO events (ts, run_id, type) SELECT '2026-09-01T00:00:00Z', 'bulk', 'bulk' FROM n;")
    subprocess.run(["sqlite3", str(db)], input="\n".join(sql), text=True, check=True)


def test_the_caddyfile_moves_only_the_events_get():
    block = re.search(r"@medulla_read_events \{(.*?)\n    \}", p._render(["events"]), re.S).group(1)
    assert block.split() == ["method", "GET", "path", "/api/v1/events"], block
    assert "@medulla_read_events" not in p._render(["notifications"])


@m.needs_cargo
@pytest.mark.skipif(not shutil.which("php"), reason="php runs Wing")
@pytest.mark.skipif(not m.AUTOLOAD.exists(), reason="wing vendor/autoload.php missing (composer install)")
@pytest.mark.skipif(not shutil.which("sqlite3"), reason="sqlite3 seeds the scratch wing.db")
def test_php_and_the_medulla_answer_every_events_read_the_same(tmp_path, monkeypatch):
    monkeypatch.setenv("NOS_HALT_FILE", str(tmp_path / "halt"))
    subprocess.run(["php", str(m.WING / "bin/init-db.php"), f"--data-dir={tmp_path}"], capture_output=True, check=True, timeout=60)
    db = tmp_path / "wing.db"
    p._seed(db)
    _seed_events(db)
    cases = [{"url": u, "headers": h, "auth": a} for u in URLS for a, h in p.AUTH.items() if u in EVERY_BEARER or a in READERS]
    exe = m._medulla(tmp_path)
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    proc, port = m._serve(exe, db)
    try:
        got = [p._medulla_get(port, c["url"], c["headers"]) for c in cases]
    finally:
        proc.kill()
        proc.wait()
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before, "a medulla read changed wing.db"
    r = subprocess.run(["php", "-d", "error_reporting=E_ALL", "-r", _PHP, str(m.AUTOLOAD), str(db), json.dumps(cases)],
                       capture_output=True, text=True, timeout=300, check=False, cwd=m.WING)
    assert r.returncode == 0, (r.stdout + r.stderr)[-4000:]
    php = json.loads(r.stdout)
    codes: dict[str, set[int]] = {}
    for c, want, (code, ctype, body) in zip(cases, php, got):
        where = f"{c['url']} as {c['auth']}"
        assert (code, ctype) == (want["code"], "application/json; charset=utf-8"), f"{where}: medulla {code} {ctype} {body[:300]} / php {want}"
        assert json.loads(body) == json.loads(want["body"]), f"{where}:\nmedulla {body[:1500]}\nphp     {want['body'][:1500]}"
        codes.setdefault(c["auth"], set()).add(code)
    # The seed reaches every outcome; a fixture gone blind would pass the comparison vacuously.
    assert set().union(*codes.values()) == {200, 401, 403}, codes
    assert (codes["face-bff, tier 1"], codes["face-bff, tier 3"], codes["thalamus, a person"]) == ({200}, {403}, {403}), codes
    read = [i for i, c in enumerate(cases) if c["auth"] == "wing.read"]
    seen = lambda url: json.loads(got[read[URLS.index(url)]][2])  # noqa: E731
    everything = seen("/api/v1/events")
    assert len(everything["items"]) == 100 and everything["total"] == BULK + len(ROWS), everything["total"]
    assert len(seen("/api/v1/events?limit=9999")["items"]) == 500 and len(seen("/api/v1/events?limit=abc")["items"]) == 1
    assert seen("/api/v1/events?run_id=0")["total"] == BULK + len(ROWS), "?run_id=0 is PHP's empty(), not a filter"
    by = {e["ts"]: e for e in seen("/api/v1/events?since=2026-10")["items"]}
    assert not {"2026-10-03T10:00:00Z", "2026-10-04T10:00:00Z", "2026-10-05T10:00:00Z"} & {t for t, e in by.items() if "result" in e}
    assert (by["2026-10-02T10:00:00Z"]["result"], by["2026-10-10T10:00:00Z"]["result"]) == (None, ["a", "b"]), by
