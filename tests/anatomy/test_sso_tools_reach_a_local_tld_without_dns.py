"""Gate: an unresolvable local-TLD name reaches the loopback edge, Host intact.

2026-10-01 Linux wet-test: every account walk failed with NameResolutionError
for auth.dev.local — Linux has no /etc/resolver, the edge listens on 127.0.0.1.
nos-smoke already retried that way; tools/nos_sso.py now does too (--insecure).
"""
import http.server
import sys
import threading
from pathlib import Path

import pytest

requests = pytest.importorskip("requests")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import nos_sso  # noqa: E402


def test_an_unresolvable_name_is_served_by_loopback_with_its_host():
    seen = {}

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            seen["host"] = self.headers.get("Host")
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    name = f"auth.nos-gate.invalid:{srv.server_port}"
    try:
        with pytest.raises(requests.exceptions.ConnectionError):
            requests.get(f"http://{name}/", timeout=5)          # red without the fallback
        nos_sso.loopback_for_unresolvable()
        nos_sso.loopback_for_unresolvable()                       # idempotent
        r = requests.get(f"http://{name}/", timeout=5)
        assert r.status_code == 200 and seen["host"] == name
    finally:
        srv.shutdown()


def test_both_sso_tools_arm_it_for_local_tlds():
    root = Path(__file__).resolve().parents[2] / "tools"
    for tool in ("nos-first-login.py", "woodpecker-token.py"):
        src = (root / tool).read_text()
        assert "if a.insecure:" in src and "loopback_for_unresolvable()" in src, tool
