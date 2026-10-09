"""--strict follows an SSO bounce with the tester instead of failing it.

Since --strict stopped taking the legacy expect set (2026-10-09), every
manifest-derived row of an SSO service (anonymous GET / -> 302 to Authentik)
read red even with tester credentials on the command line: the anonymous path
returned before the tester path could run. A bounce to the IdP IS the signal
that a row needs the tester; nothing has to declare it.
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


def _sso_service():
    state = {"logged_in": False}

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/if/flow/"):
                self.send_response(200); self.end_headers(); self.wfile.write(b"login")
            elif state["logged_in"]:
                self.send_response(200); self.end_headers(); self.wfile.write(b"app")
            else:
                self.send_response(302)
                self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}/if/flow/login/")
                self.end_headers()
        do_HEAD = do_GET

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, state


def test_strict_logs_the_tester_in_on_an_sso_bounce(monkeypatch):
    srv, state = _sso_service()
    host = f"127.0.0.1:{srv.server_port}"

    def fake_login(*a, **k):
        state["logged_in"] = True
        return True, None
    monkeypatch.setattr(smoke, "_try_authentik_login", fake_login)
    try:
        row = smoke.merge_catalog([], [{"id": "sso-app", "url": f"http://{host}/"}], {}, {})[0]
        r = smoke.probe(row, strict=True, tester_user="t", tester_password="p", authentik_domain=host)
        assert r.ok and r.status == 200, (r.status, r.error)
        state["logged_in"] = False
        bare = smoke.probe(row, strict=True, authentik_domain=host)
        assert not bare.ok, "without tester credentials the bounce stays red"
    finally:
        srv.shutdown()
