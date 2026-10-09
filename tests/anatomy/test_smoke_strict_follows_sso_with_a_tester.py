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


def test_a_row_that_asserts_the_gate_is_not_logged_in(monkeypatch):
    """geolibre expects 302 in strict: the anonymous bounce IS the verdict
    (an atlas a stranger can open leaks parcels). Following it with the tester
    read 200 and failed the row (2026-10-09, 49/50)."""
    srv, state = _sso_service()
    host = f"127.0.0.1:{srv.server_port}"

    def fake_login(*a, **k):
        state["logged_in"] = True
        return True, None
    monkeypatch.setattr(smoke, "_try_authentik_login", fake_login)
    try:
        row = smoke.merge_catalog([], [{"id": "gate", "url": f"http://{host}/",
                                        "expect": [302], "expect_strict": [302]}], {}, {})[0]
        r = smoke.probe(row, strict=True, tester_user="t", tester_password="p", authentik_domain=host)
        assert r.ok and r.status == 302, (r.status, r.error)
    finally:
        srv.shutdown()


def test_the_tester_password_is_derived_when_not_given(tmp_path, monkeypatch):
    """--strict without --tester-password reached no SSO app: the vars hold only
    the template `{{ nos_derived_secrets.nos_tester }}`. The leaf is derived the
    way tools/nos-secret.py prints it (v2), never passed on a command line."""
    import subprocess
    import sys
    sys.path.insert(0, str(REPO / "files/anatomy/module_utils"))
    import nos_secret_derive as derive
    (tmp_path / ".nos").mkdir()
    (tmp_path / ".nos/secrets.yml").write_text(
        f'nos_secret_scheme: "v2"\nnos_secret_master: "{derive.mint_master()}"\n')
    monkeypatch.setenv("HOME", str(tmp_path))
    want = subprocess.run([sys.executable, str(REPO / "tools/nos-secret.py"), "nos_tester"],
                          capture_output=True, text=True, check=True).stdout.strip()
    templ = {"nos_tester_password": "{{ nos_derived_secrets.nos_tester }}"}
    assert smoke.resolve_tester_password(None, templ) == want
    assert smoke.resolve_tester_password("cli", templ) == "cli"
    assert smoke.resolve_tester_password(None, {"nos_tester_password": "lit"}) == "lit"
