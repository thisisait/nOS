"""The identity outpost transport: one door-choosing helper, no forged identity.

dtt-per-user-tables (2026-09-07): behind KEAP_IDENTITY_URL (a unix socket that
identifies the caller by uid) every human-door tool must (1) speak over that
socket, (2) send NO X-Authentik-* header and NO proxy secret — the outpost
decides who the caller is and drops those anyway — and (3) write rows through
the human door keyed by slug, so a table's owner/tier/grants apply. Without the
variable the tools must behave exactly as before (akadmin + secret, agent-door
writes with the RW bearer), because the operator's Mac estate has no outpost.

Offline: the socket is a real AF_UNIX listener served by a tiny thread that
records what arrived and answers a fixed JSON — no KEAP, no docker.
"""
from __future__ import annotations

import http.server
import importlib
import json
import os
import pathlib
import shutil
import socketserver
import sys
import tempfile
import threading
import urllib.parse
import urllib.request

TOOLS = pathlib.Path(__file__).resolve().parents[2] / "tools"


def _short_sock() -> pathlib.Path:
    """A socket path short enough for AF_UNIX (sun_path ≤ ~104 bytes on macOS).
    pytest's tmp_path lives under a long /private/var/folders/... prefix that
    overflows the limit, so bind under a short /tmp dir instead."""
    return pathlib.Path(tempfile.mkdtemp(prefix="nid-", dir="/tmp")) / "s"


class _UnixServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    allow_reuse_address = True


def _serve(sock_path: str, seen: list[dict]):
    class H(http.server.BaseHTTPRequestHandler):
        def _reply(self, code=200, payload=None):
            body = json.dumps(payload or {"success": True, "data": {"rows": []}}).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            seen.append({"method": "GET", "path": self.path, "headers": dict(self.headers)})
            self._reply()

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
            seen.append({"method": "POST", "path": self.path, "headers": dict(self.headers), "body": body})
            self._reply(200, {"success": True, "data": body})

        def log_message(self, *a):  # quiet
            pass

    srv = _UnixServer(sock_path, H)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv


def _fresh_keap_api(monkeypatch, identity_url: str | None):
    if identity_url is None:
        monkeypatch.delenv("KEAP_IDENTITY_URL", raising=False)
    else:
        monkeypatch.setenv("KEAP_IDENTITY_URL", identity_url)
    monkeypatch.setenv("KEAP_PROXY_SHARED_SECRET", "not-for-the-wire")
    sys.path.insert(0, str(TOOLS))
    sys.modules.pop("keap_api", None)
    return importlib.import_module("keap_api")


def test_without_the_outpost_nothing_changes(monkeypatch):
    api = _fresh_keap_api(monkeypatch, None)
    assert api.via_identity() is False
    assert api.human_base().startswith("http://")
    h = api.human_headers()
    assert h["X-Authentik-Username"] == "akadmin" and h["x-keap-proxy-secret"] == "not-for-the-wire"


def test_behind_the_outpost_the_socket_carries_no_identity(monkeypatch):
    sock = _short_sock()
    seen: list[dict] = []
    srv = _serve(str(sock), seen)
    try:
        url = "http+unix://" + urllib.parse.quote(str(sock), safe="")
        api = _fresh_keap_api(monkeypatch, url)
        assert api.via_identity() and api.human_base() == url
        h = api.human_headers()
        assert not any(k.lower().startswith("x-authentik") for k in h), h
        assert "x-keap-proxy-secret" not in {k.lower() for k in h}, "the secret must never leave the outpost"
        # a read over the socket, through the installed opener
        with urllib.request.urlopen(urllib.request.Request(url + "/api/tables/roadmap/rows", headers=h), timeout=5) as r:
            assert r.status == 200
        assert seen and seen[-1]["path"] == "/api/tables/roadmap/rows"
        assert not any(k.lower().startswith("x-authentik") for k in seen[-1]["headers"])
        # a write goes to the HUMAN door keyed by slug — owner/tier/grants apply
        api.write_row("roadmap", {"slug": "dgx-probe", "title": "t", "status": "next"})
        w = seen[-1]
        assert w["method"] == "POST" and w["path"] == "/api/tables/roadmap/rows"
        assert w["body"] == {"id": "dgx-probe", "values": {"slug": "dgx-probe", "title": "t", "status": "next"}}
    finally:
        srv.shutdown()
        srv.server_close()
        shutil.rmtree(sock.parent, ignore_errors=True)


def test_write_row_refuses_a_row_without_a_slug(monkeypatch):
    sock = _short_sock()
    srv = _serve(str(sock), [])
    try:
        api = _fresh_keap_api(monkeypatch, "http+unix://" + urllib.parse.quote(str(sock), safe=""))
        try:
            api.write_row("roadmap", {"title": "no key"})
        except RuntimeError as e:
            assert "slug" in str(e)
        else:
            raise AssertionError("a slug-less row must be refused — the human door would mint a duplicate")
    finally:
        srv.shutdown()
        srv.server_close()
        shutil.rmtree(sock.parent, ignore_errors=True)
