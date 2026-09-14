#!/usr/bin/env python3
"""nOS device-gateway — loopback BFF for low-power clients.

GET /health (unauthenticated), /manifest and /tables/<id> (Authentik bearer
or GATEWAY_TOKEN host-escape). Allowlist is the security boundary; unknown
and PII table ids are 403 without calling KEAP. The KEAP agent token stays
in this process (launchd env). Devices send an Authentik access_token.

# ponytail: pairing table device-client + per-device revocation is next.

Bind is 127.0.0.1. Traefik reaches this host port; do not LAN-open.
authentik@file is the wrong gate (no browser).
"""
from __future__ import annotations

import base64
import json
import os
import ssl
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
CLIENT_ID = "nos-device-gateway"
# Host→Authentik: loopback HTTP (published authentik_port). Never derive the
# handheld's device/token URLs from this — 127.0.0.1 is the Mac, not the phone.
USERINFO = os.environ.get("AUTHENTIK_USERINFO_URL", "").strip()
# Handheld→Authentik: public issuer base, https://auth.<tld>/application/o
PUBLIC_O = os.environ.get("AUTHENTIK_PUBLIC_O_BASE", "").strip().rstrip("/")
KEAP_URL = os.environ.get("KEAP_AGENT_URL", "http://127.0.0.1:8091/agent/v1").rstrip("/")
KEAP_TOKEN = os.environ.get("KEAP_AGENT_TOKEN_RO", "")
CACHE_TTL = 30
_cache: dict[str, tuple[float, list]] = {}
_ssl = ssl.create_default_context()


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


def _oidc_base() -> str:
    """Public OIDC base advertised to devices. Never a loopback userinfo URL."""
    if PUBLIC_O:
        return PUBLIC_O
    u = USERINFO.rstrip("/")
    if u.startswith("https://") and u.endswith("/userinfo"):
        return u[: -len("/userinfo")]
    return ""


def manifest() -> dict:
    base = _oidc_base()
    device = f"{base}/device/" if base else "/application/o/device/"
    token = f"{base}/token/" if base else "/application/o/token/"
    return {
        "gateway": "nos-device-gateway",
        "explorers": [
            {"id": k, "name": v[1], "path": f"/tables/{k}", "columns": v[2]}
            for k, v in ALLOWLIST.items()
        ],
        "auth": {
            "mode": "rfc8628",
            "client_id": "nos-device-gateway",
            "scopes": ["openid", "email", "profile"],
            "device_authorization": f"POST {device}",
            "token": f"POST {token}",
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "note": (
                "RFC 8628: POST device_authorization (client_id nos-device-gateway, "
                "scope openid email profile); show verification_uri from the "
                "response; poll token until access_token. # ponytail: pairing "
                "table device-client + per-device revocation is next."
            ),
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


def _project(table_id: str, row) -> dict:
    """ALLOWLIST columns are the device's view, not the full KEAP row."""
    cols = ALLOWLIST[table_id][2]
    if not isinstance(row, dict):
        return {}
    return {k: row[k] for k in cols if k in row}


def rows_for(table_id: str) -> list:
    slug = ALLOWLIST[table_id][0]
    now = time.time()
    hit = _cache.get(table_id)
    if hit and now - hit[0] < CACHE_TTL:
        return hit[1]
    data = [_project(table_id, row) for row in _keap_rows(slug)]
    _cache[table_id] = (now, data)
    return data


def _token_is_for_this_client(access_token: str) -> bool:
    """Userinfo 200 means Authentik minted the token; azp/aud must still be us.

    A Grafana/Outline access_token also passes userinfo. Read the JWT payload
    without verifying the signature — userinfo already did that. Opaque tokens
    fail closed.
    """
    parts = access_token.split(".")
    if len(parts) != 3:
        return False
    try:
        pad = "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + pad))
    except (ValueError, json.JSONDecodeError, OSError):
        return False
    if not isinstance(payload, dict):
        return False
    if payload.get("azp") == CLIENT_ID:
        return True
    aud = payload.get("aud")
    if aud == CLIENT_ID:
        return True
    return isinstance(aud, list) and CLIENT_ID in aud


def _bearer(headers) -> str:
    header = headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[7:].strip()
    return (headers.get("X-Token", "") or "").strip()


def _userinfo_ok(access_token: str) -> str:
    """Return 'ok', 'unauthorized', or 'unavailable'."""
    req = urllib.request.Request(
        USERINFO,
        headers={"Authorization": f"Bearer {access_token}"},
        method="GET",
    )
    kwargs: dict = {"timeout": 10}
    if USERINFO.startswith("https://"):
        kwargs["context"] = _ssl
    try:
        with urllib.request.urlopen(req, **kwargs) as resp:
            return "ok" if 200 <= resp.status < 300 else "unauthorized"
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            return "unauthorized"
        return "unavailable"
    except (urllib.error.URLError, TimeoutError, OSError):
        return "unavailable"


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

    def _gate(self) -> bool:
        """True if the request may proceed. Sends 401/503 itself on failure."""
        got = _bearer(self.headers)
        if USERINFO:
            if not got:
                self._send(401, {"error": "unauthorized"})
                return False
            verdict = _userinfo_ok(got)
            if verdict == "ok":
                if not _token_is_for_this_client(got):
                    self._send(401, {"error": "unauthorized"})
                    return False
                return True
            if verdict == "unauthorized":
                self._send(401, {"error": "unauthorized"})
                return False
            self._send(503, {"error": "authentik userinfo unavailable"})
            return False
        if not TOKEN:
            self._send(503, {"error": "gateway token unset"})
            return False
        if got != TOKEN:
            self._send(401, {"error": "unauthorized"})
            return False
        return True

    def do_GET(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler
        path = self.path.split("?", 1)[0]
        if path == "/health":
            return self._send(200, {"ok": True})
        if not self._gate():
            return
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
