"""The medulla answers GET /api/v1/notifications exactly as Api\\NotificationsPresenter does (ssot/doctrine/medulla.md §5).

WHY (read set [notifications]). The app's notification surface reads this, and reading writes nothing: Bone
inserts and PHP marks read, the Caddy matcher is GET only. ?since is a plain string compare in SQL (no
strtotime), so the whole read ports. channels_json and metadata_json go through PHP's json_decode(.., true)
fallback: malformed, null and scalar JSON become [], an empty or 0..n-1-keyed object becomes a list. Parity is
measured as for the Pulse reads: the real presenter and the medulla answer one scratch wing.db x every bearer.
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
_PHP = (_pre + "  $p = new App\\Presenters\\Api\\NotificationsPresenter(new App\\Model\\NotificationRepository($db));\n"
        + _rest[_rest.index("  $p->tokenRepo"):])

#: uuid -> (severity, target, actor_action_id, read_at, superseded_at, channels_json, metadata_json, created_at)
ROWS = {
    "n-crit": ("critical", "operator", "aa-1", None, None, '["wing-inbox","ntfy"]', '{"click":"https://x/a?b=1"}', "2026-10-01 10:00:00"),
    "n-high": ("high", "operator", "aa-1", "2026-10-02T00:00:00+00:00", None, "not json", "null", "2026-10-02 10:00:00"),
    "n-med": ("medium", "operator", "0", None, "2026-10-03T00:00:00+00:00", "null", "0", "2026-10-03 10:00:00"),
    "n-low": ("low", "operator", None, None, None, "0", '"str"', "2026-10-04 10:00:00"),
    "n-info": ("info", "operator", None, None, None, "{}", "[]", "2026-10-05 10:00:00"),
    "n-list": ("info", "operator", None, None, None, '{"0":"mail","1":"ntfy"}', '{"a":{},"b":[],"c":[{}],"n":12345678901234567890}', "2026-10-06T10:00:00Z"),
    "n-keyed": ("info", "operator", None, None, None, '{"1":"ntfy","0":"mail"}', '{"k":1,"k":2,"0":"z"}', "2026-10-07 10:00:00"),
    "n-dup": ("info", "operator", None, None, None, '{"0":"a","0":"b"}', '{"x":{"0":"y","2":"w"}, "é ✓":1.5}', "2026-10-08 10:00:00"),
    "n-agent": ("high", "agent:x", "aa-1", None, None, "[]", "{}", "2026-10-09 10:00:00"),
    "n-zero": ("low", "0", None, None, None, "[]", "{}", "2026-10-09 11:00:00"),
}
BULK = 520  # info rows for the operator: limit's 500 ceiling has more than 500 rows to clamp

URLS = ["/api/v1/notifications"] + [f"/api/v1/notifications?{q}" for q in (
    "severity=high", "severity=info", "severity=0", "severity=", "severity=nope",
    "since=2026-10-04", "since=2026-10-06T10:00:00Z", "since=0", "since=",
    "actor_action_id=aa-1", "actor_action_id=0", "actor_action_id=",
    "target_actor_id=agent%3Ax", "target_actor_id=0", "target_actor_id=", "target_actor_id=nobody",
    "unread_only=1", "unread_only=0", "unread_only=", "unread_only=no",
    "limit=0", "limit=1", "limit=501", "limit=abc", "limit=3abc", "limit=", "limit=-5", "limit=1e1&limit=7",
    "severity=high&actor_action_id=aa-1&target_actor_id=agent:x", "unread_only=1&since=2026-10-02&limit=2")]


def _seed_notifications(db: pathlib.Path) -> None:
    q = lambda v: "NULL" if v is None else "'" + str(v).replace("'", "''") + "'"  # noqa: E731
    sql = [f"INSERT INTO notifications (uuid, severity, title, body, actor_id, actor_action_id, target_actor_id, channels_json, "
           f"wing_inbox_read_at, superseded_at, metadata_json, created_at) VALUES ({q(u)}, {q(s)}, 'Záloha {u} ✓', NULL, "
           f"'plugin:x', {q(aa)}, {q(t)}, {q(ch)}, {q(rd)}, {q(sup)}, {q(md)}, {q(at)});"
           for u, (s, t, aa, rd, sup, ch, md, at) in ROWS.items()]
    sql.append(f"WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < {BULK}) "
               "INSERT INTO notifications (uuid, severity, title, created_at) "
               "SELECT 'bulk-' || i, 'info', 'bulk ' || i, '2026-09-01 00:00:00' FROM n;")
    subprocess.run(["sqlite3", str(db)], input="\n".join(sql), text=True, check=True)


def test_the_caddyfile_moves_only_the_notifications_get():
    block = re.search(r"@medulla_read_notifications \{(.*?)\n    \}", p._render(["notifications"]), re.S).group(1)
    assert block.split() == ["method", "GET", "path", "/api/v1/notifications"], block
    assert "@medulla_read_notifications" not in p._render(["pulse", "inbox"])


@m.needs_cargo
@pytest.mark.skipif(not shutil.which("php"), reason="php runs Wing")
@pytest.mark.skipif(not m.AUTOLOAD.exists(), reason="wing vendor/autoload.php missing (composer install)")
@pytest.mark.skipif(not shutil.which("sqlite3"), reason="sqlite3 seeds the scratch wing.db")
def test_php_and_the_medulla_answer_every_notifications_read_the_same(tmp_path, monkeypatch):
    monkeypatch.setenv("NOS_HALT_FILE", str(tmp_path / "halt"))
    subprocess.run(["php", str(m.WING / "bin/init-db.php"), f"--data-dir={tmp_path}"], capture_output=True, check=True, timeout=60)
    db = tmp_path / "wing.db"
    p._seed(db)
    _seed_notifications(db)
    cases = [{"url": u, "headers": h, "auth": a} for u in URLS for a, h in p.AUTH.items()]
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
    op = m.yaml.safe_load(m.OPENAPI.read_text(encoding="utf-8"))["paths"]["/api/v1/notifications"]["get"]
    codes: set[int] = set()
    for c, want, (code, ctype, body) in zip(cases, php, got):
        where = f"{c['url']} as {c['auth']}"
        assert str(code) in op["responses"], f"{where}: {code} is not in wing.openapi.yml"
        assert (code, ctype) == (want["code"], "application/json; charset=utf-8"), f"{where}: medulla {code} {ctype} {body[:300]} / php {want}"
        assert p.SECRET not in body, f"a pulse env VALUE left on {where}"
        assert p._comparable(body) == p._comparable(want["body"]), f"{where}:\nmedulla {body[:1500]}\nphp     {want['body'][:1500]}"
        codes.add(code)
    # The seed reaches every outcome; a fixture gone blind would pass the comparison vacuously.
    assert codes == {200, 401, 403}, codes
    read = list(p.AUTH).index("wing.read")
    seen = lambda url: json.loads(got[URLS.index(url) * len(p.AUTH) + read][2])  # noqa: E731
    everything = seen("/api/v1/notifications")
    assert len(everything["notifications"]) == 100 and everything["total"] == BULK + 8, everything["total"]
    assert len(seen("/api/v1/notifications?limit=501")["notifications"]) == 500
    assert len(seen("/api/v1/notifications?limit=abc")["notifications"]) == 1
    unread = [n["uuid"] for n in seen("/api/v1/notifications?unread_only=1")["notifications"]]
    assert "n-med" not in unread and "n-high" not in unread and "n-crit" in unread, unread[:12]
    by = {n["uuid"]: n for n in everything["notifications"]}
    assert (by["n-list"]["channels"], by["n-keyed"]["channels"], by["n-high"]["channels"]) == (["mail", "ntfy"], {"1": "ntfy", "0": "mail"}, [])
