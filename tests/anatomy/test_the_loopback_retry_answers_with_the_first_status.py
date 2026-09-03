"""Anatomy CI gate — the smoke loopback retry does not chase redirects.

MEASURED on run 33664551853 (2026-09-03): the moment the blueprint fix gave
the outpost its providers, every forward-auth probe on the Linux runner flipped
from an honest 404 to `Temporary failure in name resolution` — the retry hit
127.0.0.1, got the outpost's 302 with an ABSOLUTE Location to auth.<tld>, and
urllib followed it to a name only the estate can resolve. A working login flow
read as a dead service, and the catalog EXPECTS 302.

The probe measures the edge's first answer. This runs a real server: a 302
pointing at a host that must never be contacted.
"""

from __future__ import annotations

import http.server
import importlib.util
import pathlib
import ssl
import threading

REPO = pathlib.Path(__file__).resolve().parents[2]


def _mod():
    spec = importlib.util.spec_from_file_location("_smoke", REPO / "tools" / "nos-smoke.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        self.send_response(302)
        # An absolute foreign Location — following it would DNS-resolve
        # a name that must not exist; .invalid is reserved to never resolve.
        self.send_header("Location", "http://forward-auth.example.invalid/login")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *a):  # silence
        pass


def test_a_302_is_the_answer_not_a_journey():
    mod = _mod()
    srv = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        status, err = mod._probe_via_loopback(
            f"http://wing.dev.local:{port}/", ssl.create_default_context(),
            timeout=5, method="GET")
    finally:
        srv.shutdown()
    assert err is None and status == 302, (
        f"got ({status}, {err!r}) — the retry chased the redirect instead of "
        "reporting the edge's own 302. Off-estate the chased name does not "
        "resolve, so a WORKING forward-auth outpost reads as a dead service")
