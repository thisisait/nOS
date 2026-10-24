"""A refused API probe says WHY: the provider's own error message, not a bare status.

2026-10-24, after a converge: llm-anthropic-api failed `400` and nothing more, in
the table and in --json ("error": null). A 400 from a provider is a dozen
different facts (no credit, a retired model id, a malformed body), each with a
different fix; the answer body names which. The probe now keeps the provider's
message (bounded), never the request or a header.
"""
from __future__ import annotations

import http.server
import importlib.util
import json
import ssl
import threading
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("nos_smoke", REPO / "tools" / "nos-smoke.py")
smoke = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(smoke)


def _serve(code: int, body: bytes):
    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass
    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _run(code, payload):
    srv = _serve(code, payload)
    try:
        entry = {"url": f"http://127.0.0.1:{srv.server_port}/v1/chat/completions", "method": "POST",
                 "body": {"model": "m", "max_tokens": 1}, "require_json": "choices", "expect": [200]}
        return smoke._probe_api(entry, ssl.create_default_context(), 5)
    finally:
        srv.shutdown()


def test_an_anthropic_refusal_names_its_reason():
    body = json.dumps({"type": "error", "error": {"type": "invalid_request_error",
                                                  "message": "Your credit balance is too low to access the Anthropic API."}})
    status, err, detail = _run(400, body.encode())
    assert status == 400 and err is None
    assert detail and "credit balance is too low" in detail and "invalid_request_error" in detail, detail


def test_an_openai_shaped_refusal_names_its_reason():
    body = json.dumps({"error": {"message": "The model `x` does not exist", "code": "model_not_found"}})
    _, _, detail = _run(404, body.encode())
    assert detail and "does not exist" in detail, detail


def test_a_non_json_refusal_keeps_a_bounded_excerpt():
    _, _, detail = _run(502, b"<html>" + b"x" * 5000 + b"</html>")
    assert detail and detail.startswith("502") and len(detail) <= 300, detail
