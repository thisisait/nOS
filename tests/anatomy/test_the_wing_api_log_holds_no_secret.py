"""Anatomy gate — Wing's /api/v1 access log records the call, never the credential.

THE JOINT (2026-10-28, row wing-to-medulla-waves wave 0). Wave 0 logs every /api/v1 request
for one release to learn who calls what before anything moves. Caddy's access log writes every
request header by default: the bearer, the session cookie, ?token= in the URI. This pins that
the file gets method, path, status, duration, and nothing an attacker could replay.

CEILING. The live half needs a frankenphp binary; CI without one runs the rendered-shape half.
"""

import json
import os
import re
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import jinja2
import pytest

REPO = Path(__file__).resolve().parents[2]
CADDY = REPO / "roles" / "pazny.wing" / "templates" / "wing.Caddyfile.j2"
SECRET = "FAKE_s3cr3t-must-not-land"


def _render(tmp: Path) -> str:
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    return env.from_string(CADDY.read_text(encoding="utf-8")).render(
        wing_log_dir=str(tmp), wing_app_dir=str(tmp),
        nos_docker_host_ip="127.0.0.1", wing_edge_token="t", medulla_routes=[], medulla_http_port=8095)


def test_the_api_log_is_bounded_and_drops_headers_and_query():
    site = _render(Path("/x")).split(":9000 {", 1)[1]
    log = re.search(r"^\s*log\s+\S+\s*\{(.*?)^\s{4}\}", site, re.M | re.S)
    assert log, "Wing's site block has no named access log"
    body = log.group(1)
    assert "/x/api-access.log" in body and "roll_size" in body and "roll_keep" in body, \
        "the api log is not its own bounded file under wing_log_dir"
    assert re.search(r"^\s*request>headers\s+delete\s*$", body, re.M), \
        "request headers (Authorization, Cookie) are not deleted from the log"
    assert re.search(r"^\s*request>uri\s+regexp\s+\\\?", body, re.M), "the query string is logged"
    assert re.search(r"^\s*log_skip\s+@\S+", site, re.M), "the log is not limited to /api/v1"


def _frankenphp():
    return shutil.which("frankenphp") or next(
        (p for p in [Path.home() / ".local/bin/frankenphp"] if p.exists()), None)


@pytest.mark.skipif(not _frankenphp(), reason="no frankenphp binary")
def test_a_logged_api_call_carries_no_credential(tmp_path):
    (tmp_path / "www").mkdir()
    (tmp_path / "www/index.php").write_text('<?php echo "php";')
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    conf = _render(tmp_path).replace(":9000 {", f":{port} {{", 1)
    (tmp_path / "Caddyfile").write_text(conf.replace("admin off", "admin off\n    persist_config off", 1))
    proc = subprocess.Popen([str(_frankenphp()), "run", "--config", str(tmp_path / "Caddyfile")],
                            cwd=tmp_path, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            env={**os.environ, "XDG_DATA_HOME": str(tmp_path), "XDG_CONFIG_HOME": str(tmp_path)})

    def get(path):
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers={
            "Authorization": f"Bearer {SECRET}", "Cookie": f"PHPSESSID={SECRET}"})
        try:
            urllib.request.urlopen(req, timeout=5).read()
        except urllib.error.HTTPError:
            pass

    log = tmp_path / "api-access.log"
    try:
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.1)
        get(f"/api/v1/probe?token={SECRET}")
        get("/dashboard")
        for _ in range(50):
            if log.exists() and log.stat().st_size:
                break
            time.sleep(0.1)
    finally:
        proc.terminate()
        proc.wait(timeout=10)
    text = log.read_text() if log.exists() else ""
    assert SECRET not in text, "a credential reached the api access log"
    rows = [json.loads(line) for line in text.splitlines()]
    assert [r["request"]["uri"] for r in rows] == ["/api/v1/probe"], f"logged: {rows}"
    assert {"status", "duration"} <= rows[0].keys() and rows[0]["request"]["method"] == "GET"
