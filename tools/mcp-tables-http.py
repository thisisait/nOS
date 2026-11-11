#!/usr/bin/env python3
"""The HTTP door to the nOS DataTables MCP (row keap-mcp-door, slice 1): read-only, as the person.

WHY. The stdio server (tools/mcp-tables-server.py) needs the caller on this host: an
estate-wide KEAP agent token or the Unix-socket identity outpost. A tool on another
machine (Open WebUI, OpenHuman, a laptop IDE) has neither. This door sits behind
Traefik forward_auth: Authentik decides who the caller is, Traefik forwards it as
X-Authentik-* and adds X-Mcp-Edge-Token, and every KEAP call goes to the HUMAN door
(/api/*) as that person with the proxy secret — exactly what the thalamus does
(as_person). No KEAP agent token is read, so none can leak into a client's config.

TRUST. Only Traefik knows the edge token: a request without it (a direct loopback
curl, another process) is refused before any identity header is read. Bind 127.0.0.1.
Writes are refused here: the write door comes with the share model.

MCP over HTTP: POST /mcp with one JSON-RPC message, answered as application/json
(the streamable-HTTP transport without a server stream); a notification gets 202.
Stdlib only, like the rest of tools/. The host organ (launchd unit, edge route,
manifest row) is the next slice of the row.

Env: NOS_MCP_EDGE_TOKEN, KEAP_PROXY_SECRET (both required: unset = 503),
     KEAP_API_URL (default http://127.0.0.1:8091), NOS_MCP_HTTP_BIND (127.0.0.1),
     NOS_MCP_HTTP_PORT (8766).
Self-check:  tools/mcp-tables-http.py --selftest   (no KEAP, no network).
"""

from __future__ import annotations

import hmac
import importlib.util
import json
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_spec = importlib.util.spec_from_file_location("mcp_tables_server", Path(__file__).with_name("mcp-tables-server.py"))
core = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(core)

MAX_BODY = 64 * 1024
USERNAME = re.compile(r"^[A-Za-z0-9._@+-]{1,150}$")
GROUP = re.compile(r"^[A-Za-z0-9 ._@+-]{1,150}$")
UID = re.compile(r"^[A-Za-z0-9-]{1,128}$")


def person(headers) -> dict | None:
    """The forwarded identity, validated; None when it is absent or malformed."""
    name = (headers.get("X-Authentik-Username") or "").strip()
    if not USERNAME.match(name):
        return None
    groups = [g.strip() for g in (headers.get("X-Authentik-Groups") or "").replace("|", ",").split(",") if g.strip()]
    if any(not GROUP.match(g) for g in groups):
        return None
    uid = (headers.get("X-Authentik-Uid") or "").strip()
    return {"username": name, "groups": groups, "uid": uid if UID.match(uid) else ""}


def door_for(who: dict):
    """tools/call for one person: read verbs over KEAP's human door, writes refused."""
    base = os.environ.get("KEAP_API_URL") or "http://127.0.0.1:8091"
    hdr = {"x-keap-proxy-secret": os.environ.get("KEAP_PROXY_SECRET", ""),
           "x-authentik-username": who["username"], "x-authentik-name": who["username"],
           "x-authentik-groups": ",".join(who["groups"])}
    if who["uid"]:
        hdr["x-authentik-uid"] = who["uid"]

    def door(args: dict) -> tuple[str, bool]:
        verb = args.get("verb", "")
        if core.VERBS.get(verb) != "read":
            return (f"verb '{verb}' is refused at the HTTP door: it is read-only "
                    "(the write door comes with the share model)"), True
        return core._human_call(args, base=base, headers=hdr)
    return door


def answer(edge_token: str | None, headers, body: bytes) -> tuple[int, dict | None]:
    """(status, json) for one POST /mcp. Pure: the selftest drives it without a socket."""
    want = os.environ.get("NOS_MCP_EDGE_TOKEN", "")
    if not want or not os.environ.get("KEAP_PROXY_SECRET"):
        return 503, {"error": "the MCP door is not wired (NOS_MCP_EDGE_TOKEN / KEAP_PROXY_SECRET unset)"}
    if not hmac.compare_digest((edge_token or "").encode(), want.encode()):
        return 403, {"error": "not through the edge"}
    who = person(headers)
    if who is None:
        return 401, {"error": "no Authentik identity on the request"}
    try:
        msg = json.loads(body or b"")
    except (ValueError, UnicodeDecodeError):
        return 400, core._err(None, -32700, "parse error")
    if not isinstance(msg, dict):
        return 400, core._err(None, -32600, "one JSON-RPC message per request")
    resp = core.handle(msg, door=door_for(who))
    return (202, None) if resp is None else (200, resp)


class Handler(BaseHTTPRequestHandler):
    server_version = "nos-mcp-tables"

    def _send(self, status: int, payload: dict | None) -> None:
        data = b"" if payload is None else json.dumps(payload).encode()
        self.send_response(status)
        if payload is not None:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:  # noqa: N802
        if self.path.split("?")[0] != "/mcp":
            return self._send(404, {"error": "POST /mcp"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return self._send(400, {"error": "bad Content-Length"})
        if n < 0 or n > MAX_BODY:
            return self._send(413, {"error": f"body over {MAX_BODY} bytes"})
        status, payload = answer(self.headers.get("X-Mcp-Edge-Token"), self.headers, self.rfile.read(n))
        self._send(status, payload)

    def do_GET(self) -> None:  # noqa: N802
        self._send(405, {"error": "no server stream; POST /mcp"})

    def log_message(self, fmt: str, *args) -> None:  # the path and status only, never headers or bodies
        sys.stderr.write("%s %s\n" % (self.command, args[1] if len(args) > 1 else ""))


def selftest() -> int:
    """The trust ladder and the read-only refusal, offline (FAKE_ values only)."""
    os.environ.update({"NOS_MCP_EDGE_TOKEN": "FAKE_edge", "KEAP_PROXY_SECRET": "FAKE_secret"})
    ok = {"X-Authentik-Username": "bob", "X-Authentik-Groups": "nos-users"}
    init = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"}).encode()
    assert answer(None, ok, init)[0] == 403
    assert answer("FAKE_wrong", ok, init)[0] == 403
    assert answer("FAKE_edge", {}, init)[0] == 401
    assert answer("FAKE_edge", {"X-Authentik-Username": "bob\r\nx: y"}, init)[0] == 401
    assert answer("FAKE_edge", {**ok, "X-Authentik-Groups": "a;rm -rf"}, init)[0] == 401
    assert answer("FAKE_edge", ok, b"{not json")[0] == 400
    assert answer("FAKE_edge", ok, b"[1]")[0] == 400
    st, r = answer("FAKE_edge", ok, init)
    assert st == 200 and r["result"]["serverInfo"]["name"] == "nos-tables", r
    note = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}).encode()
    assert answer("FAKE_edge", ok, note) == (202, None)
    for verb in ("upsert-row", "patch-field", "claim-row", "release-row"):
        call = {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {"name": "nos_tables", "arguments": {"verb": verb, "table": "t", "id": "r", "values": {"a": 1}}}}
        st, r = answer("FAKE_edge", ok, json.dumps(call).encode())
        assert st == 200 and r["result"]["isError"] and "read-only" in r["result"]["content"][0]["text"], r
    del os.environ["NOS_MCP_EDGE_TOKEN"]
    assert answer("FAKE_edge", ok, init)[0] == 503
    print("selftest OK: edge token, identity, malformed input, read-only, unwired = 503")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    bind = os.environ.get("NOS_MCP_HTTP_BIND", "127.0.0.1")
    port = int(os.environ.get("NOS_MCP_HTTP_PORT", "8766"))
    ThreadingHTTPServer((bind, port), Handler).serve_forever()
