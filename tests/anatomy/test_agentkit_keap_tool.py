"""Anatomy CI gate — mcp-keap AgentKit tool wiring (cortex Phase 6, 2026-07-11).

KEAP's loopback agent surface is the ONLY agent path to the knowledge
corpus (SEC-02: the container shares gated_net with Traefik alone, so no
container-to-container consumer exists). This gate pins the full host-side
chain — tool class, schema enum, DI registration, credential mapping,
daemon env plumbing (both platforms), and the librarian roster — so a
partial refactor can't silently strand one link of it.

Also pins the write-surface doctrine: the tool may POST only to the
proposal/moderation paths in POST_ALLOWLIST (captures, objects, lint
verdict, promotions, taxonomy propose/describe/brief) — every one a
proposal a moderator decides, never an approve path. Embeddings upserts
and lint runs belong to the keap-embed-sync / keap-lint Pulse jobs, never
to an LLM tool.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WING_APP = REPO_ROOT / "files" / "anatomy" / "wing" / "app"
TOOL_PHP = WING_APP / "AgentKit" / "Tools" / "McpKeapTool.php"
NEON = WING_APP / "config" / "common.neon"
RESOLVER = WING_APP / "AgentKit" / "Vault" / "CredentialResolver.php"
SCHEMA = REPO_ROOT / "state" / "schema" / "agent.schema.yaml"
LIBRARIAN = REPO_ROOT / "files" / "anatomy" / "agents" / "librarian" / "agent.yml"
WING_PLIST = REPO_ROOT / "roles" / "pazny.wing" / "templates" / "wing.plist.j2"
WING_ENV = REPO_ROOT / "roles" / "pazny.wing" / "templates" / "wing.env.j2"

# The whole writable KEAP surface, and every entry is a PROPOSAL a moderator
# decides. test_inspektor_librarian.py imports this to justify librarian
# holding `keap.write` — one list, two readers, so the doctrine cannot be
# widened in one file and still look narrow in the other.
PROPOSAL_ONLY_POST_PATHS = [
    "/agent/v1/captures",
    "/agent/v1/lint/verdict",
    "/agent/v1/objects",
    "/agent/v1/promotions",
    "/agent/v1/taxonomy/brief",
    "/agent/v1/taxonomy/describe",
    "/agent/v1/taxonomy/propose",
]


def keap_post_allowlist() -> list[str]:
    """POST_ALLOWLIST as the tool actually declares it."""
    m = re.search(r"POST_ALLOWLIST = \[([^\]]*)\]", TOOL_PHP.read_text(), re.DOTALL)
    assert m, "McpKeapTool must declare POST_ALLOWLIST"
    return sorted(re.findall(r"'(/[^']+)'", m.group(1)))


def test_tool_class_exists_with_id_and_scopes():
    src = TOOL_PHP.read_text()
    assert "return 'mcp-keap';" in src, "McpKeapTool::id() must return 'mcp-keap'"
    assert "'mcp.tool_use'" in src and "'keap.read'" in src, (
        "McpKeapTool::requiredScopes() must require mcp.tool_use + keap.read"
    )


def test_tool_write_surface_is_allowlisted():
    """POST is allowlisted to exactly seven proposal/moderation paths:
    captures (review queue), objects (index cards, ROADMAP S1), lint
    verdict, promotions, and the taxonomy propose/describe/brief ceremonies
    (K1 + brief, kind-tagged, moderated). Every one is a proposal a
    moderator decides — no approve path. A broader write surface
    (embeddings, lint run, admin) must NOT go through an LLM tool; widening
    this list is a doctrine change, not a refactor."""
    src = TOOL_PHP.read_text()
    paths = keap_post_allowlist()
    assert paths == PROPOSAL_ONLY_POST_PATHS, f"POST allowlist drifted: {paths}"
    assert "in_array($path, self::POST_ALLOWLIST, true)" in src, (
        "McpKeapTool must enforce the POST allowlist"
    )
    assert "str_starts_with($path, '/agent/v1/')" in src, (
        "McpKeapTool must confine paths to /agent/v1/*"
    )


def test_tool_uses_scope_split_tokens():
    """GET rides KEAP_AGENT_TOKEN_RO; POST rides KEAP_AGENT_TOKEN_RW."""
    src = TOOL_PHP.read_text()
    assert "KEAP_AGENT_TOKEN_RO" in src and "KEAP_AGENT_TOKEN_RW" in src


def test_schema_enum_contains_mcp_keap():
    assert re.search(r"^\s+- mcp-keap\b", SCHEMA.read_text(), re.MULTILINE), (
        "agent.schema.yaml tools id enum must list mcp-keap"
    )


def test_neon_registers_tool():
    neon = NEON.read_text()
    assert "register(@App\\AgentKit\\Tools\\McpKeapTool)" in neon, (
        "common.neon ToolRegistry setup must register McpKeapTool"
    )
    assert re.search(r"^\t- App\\AgentKit\\Tools\\McpKeapTool$", neon, re.MULTILINE), (
        "common.neon services must declare McpKeapTool"
    )


def test_credential_resolver_maps_scope():
    assert "'mcp-keap'" in RESOLVER.read_text(), (
        "CredentialResolver scopeToEnvName must map mcp-keap -> KEAP_AGENT_TOKEN_RO"
    )


def test_wing_daemon_env_carries_keap_tokens_on_both_platforms():
    """wing.plist.j2 (macOS launchd) and wing.env.j2 (Linux systemd --user)
    must both plumb the KEAP surface env, gated on install_keap."""
    for tmpl in (WING_PLIST, WING_ENV):
        src = tmpl.read_text()
        for key in ("KEAP_API_URL", "KEAP_AGENT_TOKEN_RO", "KEAP_AGENT_TOKEN_RW"):
            assert key in src, f"{tmpl.name} missing {key}"
        assert "install_keap" in src, f"{tmpl.name} KEAP block must be install_keap-gated"


def test_librarian_carries_keap_tool_and_scope():
    """librarian is the designated cortex consumer — its roster and scopes
    must stay in sync with the tool's requiredScopes()."""
    agent = LIBRARIAN.read_text()
    assert "- id: mcp-keap" in agent, "librarian tools roster missing mcp-keap"
    assert "- keap.read" in agent, "librarian capability_scopes missing keap.read"
    assert "- scope: mcp-keap" in agent, "librarian vault credentials missing mcp-keap"
