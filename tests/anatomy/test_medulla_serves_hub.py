"""The medulla answers GET /api/v1/hub/systems[/<id>] exactly as Api\\HubPresenter does (ssot/doctrine/medulla.md §5).

WHY (read set [hub]). The system inventory is public in PHP (SEC-7: only the POST upsert needs a bearer), so the
medulla reads no bearer, and a refused bearer must still get PHP's answer. Five filters drop on empty(), health
only on ''; enrich derives url, ip_url, domain_url and scan_state; stats count the whole table; one system carries
its children by name. ?tree and ?listed are presenter code the medulla hands back (404), and the matcher keeps away.
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
_PHP = (_pre + "  $p = new App\\Presenters\\Api\\HubPresenter();\n  $p->systems = new App\\Model\\SystemRepository($db);\n"
        + "  $p->cards = new App\\Model\\HubCardRepository();\n" + _rest[_rest.index("  $p->tokenRepo"):])

#: id, parent, name, type, category, stack, domain, port, url, priority, health_status, source
ROWS = [
    ("infra", None, "Infra", "stack", "stack", None, None, None, None, "high", "unknown", "manifest"),
    ("traefik", "infra", "Traefik ✓", "docker", "service", "infra", "traefik.example.invalid", 8080, None, "critical", "up", "manifest"),
    ("grafana", "infra", "Grafana", "docker", "service", "observability", "grafana.example.invalid", 3000, "https://custom.invalid/x",
     "medium", "down", "manifest"),
    ("mariadb", "infra", "MariaDB", "docker", "service", "infra", None, 3306, None, "high", "up", "manual"),
    ("nodomain", None, "No domain no port", "host", "service", "infra", None, None, "", "low", "unknown", "manual"),
    ("zero", None, "Zeroes", "0", "0", "0", "0", 0, "0", "0", "0", "0"),
    ("neg", None, "Negative port", "docker", "service", None, "", -1, None, "medium", "unknown", "manual"),
    ("a b", "traefik", "Space id", "docker", "service", "infra", "s.example.invalid", 1, None, "medium", "up", "manual"),
    ("child-b", "traefik", "B child", "docker", "service", "infra", None, None, None, "medium", "unknown", "manual"),
    ("child-a", "traefik", "A child", "docker", "service", "infra", None, 9, None, "medium", "unknown", "manual"),
]
LIST = "/api/v1/hub/systems"
URLS = [LIST] + [f"{LIST}?{q}" for q in (
    "stack=infra", "stack=0", "stack=", "stack=nope", "category=stack", "priority=critical", "source=manifest", "type=host",
    "health=up", "health=0", "health=", "stack=infra&health=up&type=docker", "tree=", "tree=0", "listed=0",
    "has_findings=1", "parent_id=traefik", "stack=infra&stack=observability")] + [f"{LIST}/{i}" for i in (
        "traefik", "grafana", "zero", "a%20b", "nodomain", "infra", "does-not-exist", "neg?stack=x")]
#: Public: a bearer refused anywhere else still gets PHP's answer here.
BEARERS = ("no bearer", "unknown token", "face-bff, tier 3")


def _seed_systems(db: pathlib.Path) -> None:
    q = lambda v: "NULL" if v is None else (str(v) if isinstance(v, int) else "'" + str(v).replace("'", "''") + "'")  # noqa: E731
    sql = ["PRAGMA foreign_keys=OFF;", "DELETE FROM component_scan_state;", "DELETE FROM systems;"]
    sql += [f"INSERT INTO systems (id, parent_id, name, type, category, stack, domain, port, url, priority, health_status, source, "
            f"created_at, updated_at) VALUES ({', '.join(q(v) for v in r)}, '2026-10-01 10:00:00', '2026-10-01 10:00:00');" for r in ROWS]
    sql.append("INSERT INTO component_scan_state (component_id, last_checked, findings_count, status) VALUES "
               "('traefik', '2026-10-02', 3, 'scanned'), ('grafana', NULL, 0, 'pending'), ('zero', NULL, 4, 'scanned');")
    subprocess.run(["sqlite3", str(db)], input="\n".join(sql), text=True, check=True)


def test_the_caddyfile_moves_only_the_hub_gets():
    block = re.search(r"@medulla_read_hub \{(.*?)\n    \}", p._render(["hub"]), re.S).group(1)
    assert block.split()[:3] == ["method", "GET", "path_regexp"], block
    assert "not query tree=*" in block and "not query listed=*" in block, block
    rx = re.compile(block.split()[3])
    assert rx.search(LIST) and rx.search(f"{LIST}/traefik"), block
    for path in (f"{LIST}/", f"{LIST}/a/b", f"{LIST}x", "/api/v1/hub/health"):
        assert not rx.search(path), path
    assert "@medulla_read_hub" not in p._render(["events"])


@m.needs_cargo
@pytest.mark.skipif(not shutil.which("php"), reason="php runs Wing")
@pytest.mark.skipif(not m.AUTOLOAD.exists(), reason="wing vendor/autoload.php missing (composer install)")
@pytest.mark.skipif(not shutil.which("sqlite3"), reason="sqlite3 seeds the scratch wing.db")
def test_php_and_the_medulla_answer_every_hub_read_the_same(tmp_path, monkeypatch):
    monkeypatch.setenv("NOS_HALT_FILE", str(tmp_path / "halt"))
    subprocess.run(["php", str(m.WING / "bin/init-db.php"), f"--data-dir={tmp_path}"], capture_output=True, check=True, timeout=60)
    db = tmp_path / "wing.db"
    p._seed(db)
    _seed_systems(db)
    cases = [{"url": u, "headers": p.AUTH[a], "auth": a} for u in URLS for a in BEARERS]
    exe = m._medulla(tmp_path)
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    proc, port = m._serve(exe, db)
    try:
        got = [p._medulla_get(port, c["url"], c["headers"]) for c in cases]
        handed_back = [p._medulla_get(port, f"{LIST}?{q}", {})[0] for q in ("tree=1", "listed=1")]
    finally:
        proc.kill()
        proc.wait()
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before, "a medulla read changed wing.db"
    assert handed_back == [404, 404], f"the medulla answered a ?tree or ?listed list: {handed_back}"
    r = subprocess.run(["php", "-d", "error_reporting=E_ALL", "-r", _PHP, str(m.AUTOLOAD), str(db), json.dumps(cases)],
                       capture_output=True, text=True, timeout=300, check=False, cwd=m.WING)
    assert r.returncode == 0, (r.stdout + r.stderr)[-4000:]
    php = json.loads(r.stdout)
    paths = m.yaml.safe_load(m.OPENAPI.read_text(encoding="utf-8"))["paths"]
    codes: set[int] = set()
    for c, want, (code, ctype, body) in zip(cases, php, got):
        where = f"{c['url']} as {c['auth']}"
        op = paths[LIST if c["url"].split("?")[0] == LIST else LIST + "/{id}"]
        assert str(code) in op["get"]["responses"], f"{where}: {code} is not in wing.openapi.yml"
        assert (code, ctype) == (want["code"], "application/json; charset=utf-8"), f"{where}: medulla {code} {ctype} {body[:300]} / php {want}"
        assert json.loads(body) == json.loads(want["body"]), f"{where}:\nmedulla {body[:1500]}\nphp     {want['body'][:1500]}"
        codes.add(code)
    # The seed reaches every outcome; a fixture gone blind would pass the comparison vacuously.
    assert codes == {200, 404}, codes
    seen = lambda url: json.loads(got[URLS.index(url) * len(BEARERS)][2])  # noqa: E731
    everything = seen(LIST)
    assert everything["total"] == len(ROWS) and everything["stats"]["findings"] == 7 and everything["stats"]["stacks"] == 1, everything
    one = seen(f"{LIST}/traefik")
    assert [c["id"] for c in one["children"]] == ["child-a", "child-b", "a b"] and one["scan_state"]["findings_count"] == 3, one
    assert one["url"] == "https://traefik.example.invalid", one["url"]
    assert seen(f"{LIST}?health=0")["total"] == 1 and seen(f"{LIST}?stack=0")["total"] == len(ROWS)
