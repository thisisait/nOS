"""Anatomy CI gate — mcp-tables AgentKit tool wiring (dtt harness, movement 3).

McpTablesTool is the DataTables verb surface: one tiny verb set over KEAP's
/agent/v1/tables/* so a "dumber" agent reads, searches, claims and writes a row
without ever naming a path or an HTTP method. This gate pins the host-side
chain — tool class, verb allowlist, scope-split tokens, DI registration,
credential mapping, schema enum — so a partial refactor cannot strand a link.

The design invariant it protects, distinct from McpKeapTool: the surface is
VERB-shaped, not path-shaped. An agent may reach exactly the eight verbs below
and nothing else — there is no `path`/`method` input to probe around. The verb
map IS the write allowlist.

What this gate cannot see: that search-rows actually floors on a real cosine
distance and returns NONE below it — that law lives in KEAP
(server/agent-table-search.test.ts) and the live estate, not in this thin
host-side wrapper.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WING_APP = REPO_ROOT / "files" / "anatomy" / "wing" / "app"
TOOL_PHP = WING_APP / "AgentKit" / "Tools" / "McpTablesTool.php"
NEON = WING_APP / "config" / "common.neon"
RESOLVER = WING_APP / "AgentKit" / "Vault" / "CredentialResolver.php"
SCHEMA = REPO_ROOT / "state" / "schema" / "agent.schema.yaml"

# The eight verbs, split by plane. Reads ride the RO token, writes the RW token.
READ_VERBS = ["list-tables", "read-rows", "get-row", "search-rows"]
WRITE_VERBS = ["upsert-row", "patch-field", "claim-row", "release-row"]


def verb_map() -> dict[str, str]:
    """The VERBS const as the tool actually declares it: verb => plane."""
    src = TOOL_PHP.read_text()
    m = re.search(r"const VERBS = \[(.*?)\];", src, re.DOTALL)
    assert m, "McpTablesTool must declare a VERBS map"
    return dict(re.findall(r"'([a-z-]+)' => '(read|write)'", m.group(1)))


def test_tool_id_and_scopes():
    src = TOOL_PHP.read_text()
    assert "return 'mcp-tables';" in src, "McpTablesTool::id() must return 'mcp-tables'"
    for scope in ("'mcp.tool_use'", "'keap.read'", "'keap.write'"):
        assert scope in src, f"requiredScopes() must include {scope}"


def test_the_verb_map_is_the_allowlist():
    """Exactly eight verbs, split read/write as declared. Adding a verb is a
    deliberate surface change, not a refactor."""
    vm = verb_map()
    assert sorted(vm) == sorted(READ_VERBS + WRITE_VERBS), f"verb set drifted: {sorted(vm)}"
    for v in READ_VERBS:
        assert vm[v] == "read", f"{v} must ride the read plane"
    for v in WRITE_VERBS:
        assert vm[v] == "write", f"{v} must ride the write plane"


def test_the_surface_is_verb_shaped_not_path_shaped():
    """The anti-McpKeapTool property: an agent gives an INTENT, never a URL.
    The input schema exposes `verb` (an enum) and no raw path/method."""
    src = TOOL_PHP.read_text()
    assert "'verb' => ['type' => 'string', 'enum' =>" in src, (
        "the input schema must expose a `verb` enum"
    )
    m = re.search(r"inputSchema: \[(.*?)\n\t\t\t\],", src, re.DOTALL)
    props = m.group(1) if m else src
    assert "'path'" not in props and "'method'" not in props, (
        "McpTablesTool must not expose a raw path/method — that is McpKeapTool's "
        "surface; the whole point here is that the agent never names a URL"
    )


def test_scope_split_tokens():
    """Reads ride KEAP_AGENT_TOKEN_RO; writes ride KEAP_AGENT_TOKEN_RW."""
    src = TOOL_PHP.read_text()
    assert "KEAP_AGENT_TOKEN_RO" in src and "KEAP_AGENT_TOKEN_RW" in src


def test_neon_registers_tool():
    neon = NEON.read_text()
    assert "register(@App\\AgentKit\\Tools\\McpTablesTool)" in neon, (
        "common.neon ToolRegistry setup must register McpTablesTool"
    )
    assert re.search(r"^\t- App\\AgentKit\\Tools\\McpTablesTool$", neon, re.MULTILINE), (
        "common.neon services must declare McpTablesTool"
    )


def test_credential_resolver_maps_scope():
    assert "'mcp-tables'" in RESOLVER.read_text(), (
        "CredentialResolver scopeToEnvName must map mcp-tables -> KEAP_AGENT_TOKEN_RO "
        "(else the fallback yields MCP_TABLES, an env var nothing sets)"
    )


def test_schema_enum_contains_mcp_tables():
    assert re.search(r"^\s+- mcp-tables\b", SCHEMA.read_text(), re.MULTILINE), (
        "agent.schema.yaml tools id enum must list mcp-tables, or no agent can "
        "declare it"
    )
