#!/usr/bin/env python3
"""nOS device-gateway — loopback BFF for low-power clients.

GET /health, /manifest, /tables/<id>. Allowlist is the security boundary;
unknown and PII table ids are 403 without calling KEAP. The KEAP agent
token stays in this process (launchd env). Devices send GATEWAY_TOKEN.

# ponytail: replace GATEWAY_TOKEN with RFC 8628 when authentik-device-flow lands.

Bind is 127.0.0.1 this slice. Do not LAN-open; Traefik is skipped until
the device-code gate exists. Forward-auth is the wrong gate (no browser).
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Handheld prototype ids. invoice/party/journal-entry/account/kolben-* stay out.
ALLOWLIST = {
    "roadmap": ("roadmap", "nOS Roadmap", ["slug", "status", "track", "title"]),
    "current-state": ("current-state", "Claim board", ["slug", "status", "title"]),
    "todos-akadmin": ("todos-akadmin", "Todos", ["completed", "title"]),
    "repo": ("repo", "Repositories", ["slug", "status", "track", "title"]),
    "application": ("application", "Applications", ["slug", "status", "title"]),
    "package": ("package", "Packages", ["slug", "status", "title"]),
}

BIND = "127.0.0.1"
PORT = int(os.environ.get("GATEWAY_PORT", "8770"))
TOKEN = os.environ.get("GATEWAY_TOKEN", "")
KEAP_URL = os.environ.get("KEAP_AGENT_URL", "http://127.0.0.1:8091/agent/v1").rstrip("/")
KEAP_TOKEN = os.environ.get("KEAP_AGENT_TOKEN_RO", "")
CACHE_TTL = 30
_cache: dict[str, tuple[float, list]] = {}


def table_id_of(path: str) -> str | None:
    if path == "/roadmap.json":
        return "roadmap"
    if path == "/board.json":
        return "current-state"
    if path.startswith("/tables/"):
        return path[len("/tables/") :].strip("/")
    return None


def is_allowed(table_id: str) -> bool:
    return table_id in ALLOWLIST


def manifest() -> dict:
    return {
        "gateway": "nos-device-gateway",
        "explorers": [
            {"id": k, "name": v[1], "path": f"/tables/{k}", "columns": v[2]}
            for k, v in ALLOWLIST.items()
        ],
        "auth": {
            "mode": "bearer",
            # ponytail: replace with RFC 8628 when authentik-device-flow lands
            "note": "shared bearer until authentik device-code + per-device scope",
        },
    }


def _keap_rows(slug: str) -> list:
    if not KEAP_TOKEN:
        raise RuntimeError("KEAP_AGENT_TOKEN_RO is unset — fail-closed")
    url = f"{KEAP_URL}/tables/{slug}/rows"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {KEAP_TOKEN}"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        payload = json.loads(resp.read().decode())
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        raise RuntimeError("KEAP rows response was not an object")
    rows = payload.get("rows")
    if rows is None and isinstance(payload.get("data"), dict):
        rows = payload["data"].get("rows")
    if rows is None:
        rows = payload.get("data")
    if not isinstance(rows, list):
        raise RuntimeError("KEAP rows response had no array")
    return rows


def rows_for(table_id: str) -> list:
    slug = ALLOWLIST[table_id][0]
    now = time.time()
    hit = _cache.get(table_id)
    if hit and now - hit[0] < CACHE_TTL:
        return hit[1]
    data = _keap_rows(slug)
    _cache[table_id] = (now, data)
    return data


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args) -> None:
        return

    def _send(self, code: int, obj) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authed(self) -> bool:
        if not TOKEN:
            return False
        header = self.headers.get("Authorization", "")
        got = header[7:] if header.startswith("Bearer ") else self.headers.get("X-Token", "")
        return got == TOKEN

    def do_GET(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler
        path = self.path.split("?", 1)[0]
        if path == "/health":
            return self._send(200, {"ok": True})
        if not TOKEN:
            return self._send(503, {"error": "gateway token unset"})
        if not self._authed():
            return self._send(401, {"error": "unauthorized"})
        if path == "/manifest":
            return self._send(200, manifest())
        table_id = table_id_of(path)
        if table_id is None:
            return self._send(404, {"error": "not found"})
        if not is_allowed(table_id):
            return self._send(403, {"error": "table not exposed to devices"})
        try:
            data = rows_for(table_id)
        except Exception as exc:
            return self._send(500, {"error": str(exc)})
        self._send(200, data)


def main() -> int:
    httpd = ThreadingHTTPServer((BIND, PORT), Handler)
    print(f"device-gateway listening on {BIND}:{PORT}", file=sys.stderr)
    httpd.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
