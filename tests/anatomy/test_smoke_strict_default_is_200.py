"""`nos-smoke --strict` accepts only 200/204 unless a row says otherwise.

merge_catalog() and derive_from_manifest() wrote the LEGACY default expect set
[200, 301, 302, 308] into every row, so probe() saw it as the row's own choice
and --strict never reached its documented [200, 204]: a bounce to the Authentik
login read as green on every SSO service (found 2026-10-09).
"""
from __future__ import annotations

import http.server
import importlib.util
import pathlib
import threading

REPO = pathlib.Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("nos_smoke", REPO / "tools/nos-smoke.py")
smoke = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(smoke)


class _Bounce(http.server.BaseHTTPRequestHandler):
    def _bounce(self):
        self.send_response(302)
        self.send_header("Location", "/application/o/authorize/?client_id=x")
        self.end_headers()
    do_GET = do_HEAD = _bounce

    def log_message(self, *a):
        pass


def _serve():
    srv = http.server.HTTPServer(("127.0.0.1", 0), _Bounce)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _catalog_row(url):
    return smoke.merge_catalog([], [{"id": "t", "url": url}], {}, {})[0]


def test_strict_refuses_a_bounce_to_the_login_on_a_defaulted_row():
    srv = _serve()
    try:
        url = f"http://127.0.0.1:{srv.server_port}/"
        r = smoke.probe(_catalog_row(url), strict=True)
        assert r.status == 302 and not r.ok, \
            "a row with no expect/expect_strict must not accept a 302 under --strict"
        assert smoke.probe(_catalog_row(url), strict=False).ok, \
            "legacy mode keeps the wide default (a bounce proves the router is alive)"
    finally:
        srv.shutdown()


def test_a_row_that_declares_expect_still_wins_in_strict():
    srv = _serve()
    try:
        url = f"http://127.0.0.1:{srv.server_port}/"
        row = smoke.merge_catalog([], [{"id": "t", "url": url, "expect": [302]}], {}, {})[0]
        assert smoke.probe(row, strict=True).ok
    finally:
        srv.shutdown()
