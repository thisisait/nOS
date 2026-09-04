#!/usr/bin/env python3
"""A stdio MCP server that gives external agents the nOS DataTables verb surface.

WHY THIS EXISTS, and why NOT mcpo. AgentKit agents (MiniMax, local models) reach
DataTables in-process via App\\AgentKit\\Tools\\McpTablesTool. External coding
agents — Cursor, Codex, Claude Code — are MCP *clients* and need an MCP *server*
to connect to. The estate's `mcpo` (roles/pazny.mcp_gateway) goes the OTHER way:
it wraps MCP servers and exposes them as OpenAPI REST for Open WebUI, and it
cannot even reach KEAP (SEC-02 gated_net; see McpKeapTool's docstring). So the
external door is a dedicated stdio server — this one — that proxies the same
eight verbs to KEAP's loopback `/agent/v1/tables/*`, honouring the same tokens.

It presents ONE tool, `nos_tables`, with the SAME verb-shaped input as the
in-process McpTablesTool, so both consumers speak one contract over one store.

STDLIB ONLY, like every other reader in tools/. MCP stdio is newline-delimited
JSON-RPC 2.0, and a tools-only server needs exactly initialize / tools/list /
tools/call — small enough to do correctly without the `mcp` SDK (which is not
installed and would break the tools/ no-deps convention).

Register it with an IDE by pointing its MCP config at this script, e.g. Claude
Code:  claude mcp add nos-tables -- python3 /ABS/PATH/tools/mcp-tables-server.py
with KEAP_API_URL + KEAP_AGENT_TOKEN_RO/RW in the environment. See
docs/plans/datatables-subsystem.md for the access model these tokens carry.

Self-check:  tools/mcp-tables-server.py --selftest   (no KEAP needed).
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

PROTOCOL_VERSION = "2025-06-18"  # echoed back to a client that speaks it; see initialize
SERVER_INFO = {"name": "nos-tables", "version": "1"}

# verb => plane. The plane picks the token; the map is the write allowlist. This
# mirrors McpTablesTool::VERBS — one contract, two consumers.
VERBS = {
    "list-tables": "read",
    "read-rows": "read",
    "get-row": "read",
    "search-rows": "read",
    "upsert-row": "write",
    "patch-field": "write",
    "claim-row": "write",
    "release-row": "write",
}

TOOL_SCHEMA = {
    "type": "object",
    "required": ["verb"],
    "properties": {
        "verb": {"type": "string", "enum": list(VERBS)},
        "table": {"type": "string", "description": "Table slug, e.g. \"roadmap\". Required for every verb except list-tables."},
        "id": {"type": "string", "description": "Row __id. Required for get-row/patch-field/claim-row/release-row; optional for upsert-row (present = update, absent = insert)."},
        "q": {"type": "string", "description": "Query text for search-rows."},
        "limit": {"type": "integer", "description": "Max results for search-rows / read-rows (server caps at 50)."},
        "values": {"type": "object", "description": "Column key->value map for upsert-row."},
        "field": {"type": "string", "description": "Single column key for patch-field."},
        "value": {"description": "New value for patch-field (any JSON type)."},
    },
}

TOOL_DESCRIPTION = (
    "Work nOS DataTables (roadmap, apps, systems, ...) through one small verb set. "
    "A row is addressed by its __id (returned by every read). search-rows finds rows "
    "by MEANING and returns NOTHING below a confidence floor — an empty result is a "
    "real \"no match\", not the nearest wrong row. Writes are upsert-shaped (give __id "
    "to update, omit it to insert). claim-row takes a cooperative lease so two agents "
    "do not both edit one row."
)


def _base_url() -> str:
    return (os.environ.get("KEAP_API_URL") or "http://127.0.0.1:8091").rstrip("/")


def _route(args: dict) -> tuple[str, str, dict | None, str | None]:
    """verb -> (method, path, body|None, error|None). Mirrors McpTablesTool::route."""
    verb = args.get("verb", "")
    if verb not in VERBS:
        return "GET", "", None, "verb must be one of: " + ", ".join(VERBS)
    table = str(args.get("table") or "").strip()
    if verb != "list-tables" and not table:
        return "GET", "", None, f"verb '{verb}' needs a `table`"
    rid = str(args.get("id") or "").strip()
    t = urllib.parse.quote(table, safe="")
    rows = f"/agent/v1/tables/{t}/rows"

    def need_id() -> str | None:
        return f"verb '{verb}' needs an `id`" if not rid else None

    if verb == "list-tables":
        return "GET", "/agent/v1/tables", None, None
    if verb == "read-rows":
        limit = int(args.get("limit") or 0)
        return "GET", rows + (f"?limit={limit}" if limit > 0 else ""), None, None
    if verb == "get-row":
        return "GET", f"{rows}/{urllib.parse.quote(rid, safe='')}", None, need_id()
    if verb == "search-rows":
        q = str(args.get("q") or "").strip()
        if not q:
            return "GET", "", None, "verb 'search-rows' needs a `q`"
        query = {"q": q}
        if int(args.get("limit") or 0) > 0:
            query["limit"] = str(int(args["limit"]))
        return "GET", f"/agent/v1/tables/{t}/search?" + urllib.parse.urlencode(query), None, None
    if verb == "upsert-row":
        values = args.get("values")
        if not isinstance(values, dict) or not values:
            return "POST", rows, None, "verb 'upsert-row' needs a non-empty `values` object"
        body = dict(values)
        if rid:
            body["__id"] = rid  # how the door routes a write to an existing row
        return "POST", rows, body, None
    if verb == "patch-field":
        field = str(args.get("field") or "").strip()
        if not rid or not field:
            return "POST", rows, None, "verb 'patch-field' needs an `id` and a `field`"
        return "POST", rows, {"__id": rid, field: args.get("value")}, None
    if verb == "claim-row":
        return "POST", f"{rows}/{urllib.parse.quote(rid, safe='')}/claim", None, need_id()
    if verb == "release-row":
        return "POST", f"{rows}/{urllib.parse.quote(rid, safe='')}/release", None, need_id()
    return "GET", "", None, f"unknown verb '{verb}'"  # unreachable


def _call_keap(args: dict) -> tuple[str, bool]:
    """Dispatch one verb to the KEAP door. Returns (text, is_error)."""
    method, path, body, err = _route(args)
    if err is not None:
        return err, True
    plane = VERBS[args["verb"]]
    var = "KEAP_AGENT_TOKEN_RW" if plane == "write" else "KEAP_AGENT_TOKEN_RO"
    token = os.environ.get(var) or ""
    if not token:
        return f"{var} is not set — KEAP agent surface unreachable", True

    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(_base_url() + path, data=data, method=method)
    req.add_header("Accept", "application/json")
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("X-Keap-Agent", os.environ.get("NOS_MCP_AGENT", "external"))
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = resp.read().decode("utf-8", "replace")
            return f"HTTP {resp.status}\n{payload}", resp.status >= 400
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", "replace")
        return f"HTTP {exc.code}\n{payload}", True
    except urllib.error.URLError as exc:
        return f"KEAP unreachable at {_base_url()}: {exc.reason}", True


def handle(msg: dict) -> dict | None:
    """One JSON-RPC message -> one response (or None for a notification)."""
    method = msg.get("method")
    mid = msg.get("id")

    if method == "initialize":
        want = (msg.get("params") or {}).get("protocolVersion")
        return _ok(mid, {
            "protocolVersion": want or PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        })
    if method == "notifications/initialized":
        return None  # notification: no reply
    if method == "tools/list":
        return _ok(mid, {"tools": [{
            "name": "nos_tables",
            "description": TOOL_DESCRIPTION,
            "inputSchema": TOOL_SCHEMA,
        }]})
    if method == "tools/call":
        params = msg.get("params") or {}
        if params.get("name") != "nos_tables":
            return _err(mid, -32602, f"unknown tool {params.get('name')!r}")
        text, is_error = _call_keap(params.get("arguments") or {})
        return _ok(mid, {"content": [{"type": "text", "text": text}], "isError": is_error})
    if method == "ping":
        return _ok(mid, {})
    if mid is None:
        return None  # an unknown notification is ignored, not answered
    return _err(mid, -32601, f"method not found: {method}")


def _ok(mid, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _err(mid, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


def serve() -> None:
    """Newline-delimited JSON-RPC over stdio — the MCP stdio transport."""
    out = sys.stdout
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue  # not our frame; the transport drops it
        resp = handle(msg)
        if resp is not None:
            out.write(json.dumps(resp) + "\n")
            out.flush()


def selftest() -> int:
    """Drive the handler in-process — no KEAP, no stdio. Proves the protocol
    shape: initialize echoes the version, tools/list carries all eight verbs,
    and a bad verb is a fail-soft tool error, not a crash."""
    init = handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                   "params": {"protocolVersion": "2025-06-18"}})
    assert init["result"]["protocolVersion"] == "2025-06-18", init
    assert init["result"]["serverInfo"]["name"] == "nos-tables", init

    assert handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None

    listed = handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    tools = listed["result"]["tools"]
    assert len(tools) == 1 and tools[0]["name"] == "nos_tables", listed
    enum = tools[0]["inputSchema"]["properties"]["verb"]["enum"]
    assert set(enum) == set(VERBS), enum

    # A routing bad-verb is caught before any HTTP, as a tool error.
    text, is_err = _call_keap({"verb": "drop-everything"})
    assert is_err and "verb must be one of" in text, (text, is_err)

    # Every verb routes to a sane (method, path) without touching the network.
    for verb in VERBS:
        args = {"verb": verb, "table": "roadmap", "id": "r1", "q": "x",
                "field": "status", "value": "done", "values": {"a": 1}}
        method, path, _body, err = _route(args)
        assert err is None, (verb, err)
        assert path.startswith("/agent/v1/"), (verb, path)
        assert method in ("GET", "POST"), (verb, method)

    # An unknown JSON-RPC method for a request gets a -32601; a notification does not.
    assert handle({"jsonrpc": "2.0", "id": 9, "method": "nope"})["error"]["code"] == -32601
    assert handle({"jsonrpc": "2.0", "method": "nope"}) is None

    print("selftest OK: protocol shape + all 8 verbs route + fail-soft bad verb")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    serve()
