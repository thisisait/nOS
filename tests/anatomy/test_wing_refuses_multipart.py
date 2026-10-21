"""Anatomy gate — Wing refuses multipart bodies before PHP parses them.

THE SYMPTOM (2026-10-21). Reports of a heap use-after-free in PHP's multipart
(rfc1867) path: upload_progress Off closes only the session handler, the parser
still runs on every multipart POST. Wing's auth (edge token, bearer, HMAC) is
PHP code, so 127.0.0.1:9000 and the docker bridge reach the parser pre-auth for
every local user and container. Wing reads no uploads ($_FILES nowhere).

THE FIX. Caddy answers any Content-Type naming multipart with 415 and closes,
so no body reaches PHP whoever sends it, through Traefik or not.

CEILING. The live half needs a frankenphp binary (PATH or ~/.local/bin); CI
without one runs the rendered-shape half only.
"""

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


def _render(tmp: Path) -> str:
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    return env.from_string(CADDY.read_text(encoding="utf-8")).render(
        wing_log_dir=str(tmp), wing_app_dir=str(tmp),
        nos_docker_host_ip="127.0.0.1", wing_edge_token="t")


def test_the_site_refuses_multipart():
    site = _render(Path("/x")).split(":9000 {", 1)[1]
    m = re.search(r"^\s*@(\S+)\s+header_regexp\s+Content-Type\s+\(\?i\)multipart\s*$", site, re.M)
    assert m, "no case-insensitive multipart matcher in Wing's site block"
    assert re.search(rf"^\s*respond\s+@{m.group(1)}\b.*\b4\d\d\b", site, re.M), \
        "the multipart matcher does not answer 4xx"


def _frankenphp():
    return shutil.which("frankenphp") or next(
        (p for p in [Path.home() / ".local/bin/frankenphp"] if p.exists()), None)


@pytest.mark.skipif(not _frankenphp(), reason="no frankenphp binary")
def test_a_multipart_post_never_reaches_php(tmp_path):
    (tmp_path / "www").mkdir()
    (tmp_path / "www/index.php").write_text('<?php touch(__DIR__."/../hit"); echo "php";')
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    conf = _render(tmp_path).replace(":9000 {", f":{port} {{", 1)
    (tmp_path / "Caddyfile").write_text(conf.replace("admin off", "admin off\n    persist_config off", 1))
    proc = subprocess.Popen([str(_frankenphp()), "run", "--config", str(tmp_path / "Caddyfile")],
                            cwd=tmp_path, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            env={**os.environ, "XDG_DATA_HOME": str(tmp_path), "XDG_CONFIG_HOME": str(tmp_path)})

    def post(ctype, body=b"--x\r\nContent-Disposition: form-data; name=a\r\n\r\n1\r\n--x--\r\n"):
        req = urllib.request.Request(f"http://127.0.0.1:{port}/", data=body, headers={"Content-Type": ctype})
        try:
            return urllib.request.urlopen(req, timeout=5).status
        except urllib.error.HTTPError as e:
            return e.code

    try:
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.1)
        for ctype in ("multipart/form-data; boundary=x", "MULTIPART/Form-Data; boundary=x"):
            assert post(ctype) == 415, ctype
            assert not (tmp_path / "hit").exists(), f"PHP ran for {ctype}"
        assert post("application/json", b"{}") == 200, "a JSON POST no longer reaches PHP"
    finally:
        proc.terminate()
        proc.wait(timeout=10)
