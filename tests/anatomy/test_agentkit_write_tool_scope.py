"""Anatomy SECURITY gate — AgentKit gated file-write tool (Q8/A1, 2026-06-16).

This is the security-critical gate for adjustment step A1. It pins the
structural invariants of MigrationWriteTool.php — the AgentKit tool that lets
the native migration-author author a migration YAML + bump default.config.yml.

The single security invariant it enforces (and the wall behind A1):

    The write tool makes NOTHING live. It writes ONLY into the working tree,
    to EXACTLY two targets — a migration YAML under files/anatomy/migrations/
    and default.config.yml — and nothing else, ever. The review MR
    (tools/migration-pr.sh → local GitLab forge) + operator merge (GATE 2)
    remains the boundary, unchanged from the CLI path. AgentKit gains
    visibility (sessions/spans/dashboard), not reach.

Mirrors tests/anatomy/test_security_agentkit_a141.py: static source
inspection (regex), NO PHP interpreter — runs in CI without PHP. The gate
MUST prove escape-refusal: traversal, absolute, and symlink escape are all
structurally refused; there is no shell/exec; the scope is required; and
$content is never leaked into audit metadata.

Also asserts the registration triangle (schema enum ↔ impl class ↔ DI
factory + service-list) so the tool is reachable end-to-end.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
WING_APP = REPO_ROOT / "files" / "anatomy" / "wing" / "app"
WRITE_TOOL = WING_APP / "AgentKit" / "Tools" / "MigrationWriteTool.php"
COMMON_NEON = WING_APP / "config" / "common.neon"
AGENT_SCHEMA = REPO_ROOT / "state" / "schema" / "agent.schema.yaml"
MIGRATION_AUTHOR_DIR = REPO_ROOT / "files" / "anatomy" / "agents" / "migration-author" / "agent.yml"


@pytest.fixture(scope="module")
def src() -> str:
    if not WRITE_TOOL.is_file():
        pytest.fail("MigrationWriteTool.php is missing — A1 not implemented")
    return WRITE_TOOL.read_text()


def _strip_php_comments_and_strings(src: str) -> str:
    """Remove PHP block + line comments AND single/double-quoted string
    literals so a no-shell scan tests the actual CODE — not prose in a
    docstring nor markdown backticks inside the LLM-facing description string.
    A forbidden primitive surviving this strip is a real call site.

    Crude but sufficient for a static gate: drops /* */, //, # to EOL, then
    '...' and "..." (no nested-escape handling needed — the source has none)."""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    src = re.sub(r"//[^\n]*", "", src)
    src = re.sub(r"(?m)^\s*#[^\n]*", "", src)
    # Single-quoted: no escaped-quote in this source, so [^']* is safe.
    src = re.sub(r"'[^']*'", "''", src)
    src = re.sub(r'"[^"]*"', '""', src)
    return src


# ---------- identity + scope ----------


def test_tool_id_is_migration_file_write(src: str):
    """The tool id is migration-file-write, NEVER bash-write. bash-write is a
    forbidden/negative token in test_agentkit_dreams.py; registering a real
    bash-write would tangle that gate AND advertise a general shell-write
    capability this tool deliberately does not have."""
    assert re.search(
        r"function\s+id\s*\(\s*\)\s*:\s*string\s*\{\s*return\s+'migration-file-write'\s*;",
        src,
    ), "id() must return 'migration-file-write'"
    # bash-write must NOT be the id of this tool.
    assert "'bash-write'" not in src, (
        "MigrationWriteTool.php must not reference 'bash-write' — wrong id, "
        "tangles the dreams gate"
    )


def test_requires_migration_write_scope(src: str):
    """requiredScopes() returns nos.migration.write — the registry's
    scope-gate is the structural admission control (session won't start
    without it)."""
    m = re.search(r"function\s+requiredScopes\s*\([^)]*\)\s*:\s*array\s*\{(.+?)\}", src, re.DOTALL)
    assert m, "requiredScopes() not found"
    assert "'nos.migration.write'" in m.group(1), (
        "requiredScopes() must return 'nos.migration.write'"
    )


# ---------- the allowlist: EXACTLY two targets ----------


def test_allowlist_is_exactly_two_targets(src: str):
    """The write surface is exactly files/anatomy/migrations/ + default.config.yml.
    No other writable location may be named — refuse if any obvious escape
    target leaks in as a writable path."""
    assert "files/anatomy/migrations" in src, (
        "MigrationWriteTool.php must name files/anatomy/migrations as an allowed target"
    )
    assert "default.config.yml" in src, (
        "MigrationWriteTool.php must name default.config.yml as an allowed target"
    )
    # No other directory should appear as a writable allowlist target. These
    # are the dangerous sibling dirs an escape would aim for.
    for forbidden in ("/etc/", "roles/", "templates/", "credentials.yml",
                      "default.credentials.yml", "files/anatomy/plugins"):
        assert forbidden not in src, (
            f"MigrationWriteTool.php names '{forbidden}' — the allowlist must be "
            "EXACTLY two targets (migrations dir + default.config.yml)"
        )


# ---------- escape refusal (the load-bearing security logic) ----------


def test_rejects_traversal(src: str):
    """A '..' (or '.') path segment is refused — no traversal out of the tree."""
    assert "'..'" in src, "MigrationWriteTool.php has no '..' traversal refusal"
    assert "traversal" in src, "refusal reason 'traversal' missing"


def test_rejects_absolute_input(src: str):
    """An absolute path (leading '/') is refused — input is repo-relative only."""
    assert re.search(r"str_starts_with\s*\(\s*\$path\s*,\s*'/'\s*\)", src), (
        "MigrationWriteTool.php does not refuse absolute paths via "
        "str_starts_with($path, '/')"
    )
    assert "absolute" in src, "refusal reason 'absolute' missing"


def test_uses_realpath_containment(src: str):
    """Symlink escape is refused via realpath canonicalisation of the PARENT
    dir (the file may not exist yet) + a containment check. This is the
    BashReadOnlyTool realpath idiom applied to the parent."""
    assert "realpath(" in src, "MigrationWriteTool.php must use realpath() for containment"
    assert "dirname(" in src, (
        "MigrationWriteTool.php must canonicalise the PARENT dir (dirname()) — "
        "the target file may not exist yet"
    )
    assert "symlink_escape" in src, "refusal reason 'symlink_escape' missing"


def test_migration_filename_pattern_enforced(src: str):
    """The migration filename is shape-checked <YYYY-MM-DD>-<slug>.yml so a
    path can't smuggle in arbitrary basenames."""
    assert re.search(r"\\d\{4\}-\\d\{2\}-\\d\{2\}", src), (
        "MigrationWriteTool.php does not enforce the <YYYY-MM-DD> migration "
        "filename regex"
    )


def test_content_size_capped(src: str):
    """A content size cap refuses a runaway write."""
    assert "MAX_CONTENT_BYTES" in src, "MigrationWriteTool.php has no MAX_CONTENT_BYTES cap"


# ---------- NO shell, NO process spawn ----------


def test_no_shell_no_exec(src: str):
    """This is a PURE file write — it must NEVER spawn a process. None of the
    shell/exec primitives may appear IN CODE (that is exactly the reach the
    security model forbids inside AgentKit). Comments are stripped first so the
    class docstring may legitimately *name* these primitives to say it has
    none of them."""
    code = _strip_php_comments_and_strings(src)
    forbidden = ["proc_open", "exec(", "shell_exec", "system(", "passthru", "popen", "`"]
    present = [tok for tok in forbidden if tok in code]
    assert not present, (
        f"MigrationWriteTool.php contains process-spawn primitives {present} in CODE — "
        "the write tool must be a pure file write, never a shell/exec surface"
    )


# ---------- fail-soft + audit metadata ----------


def test_fail_soft(src: str):
    """Every refusal returns ToolResult::error (fail-soft) so the LLM
    self-corrects rather than crashing the session."""
    assert "ToolResult::error" in src, (
        "MigrationWriteTool.php must fail-soft via ToolResult::error on refusal"
    )


def test_metadata_carries_path_and_refusal(src: str):
    """The audit metadata carries path_written (success) + refused_reason
    (refusal) so a single SELECT WHERE actor_action_id=? reconstructs every
    write + every refusal."""
    assert "path_written" in src, "success metadata must carry 'path_written'"
    assert "refused_reason" in src, "refusal metadata must carry 'refused_reason'"


def test_never_writes_content_into_metadata(src: str):
    """Audit-leak guard: $content must NEVER land in metadata. The
    agent_tool_use event already echoes the input (acceptable —
    pii_classification: none, migration records carry no secrets); the result
    metadata must not duplicate the full content into the audit row."""
    assert "'content' => $content" not in src, (
        "MigrationWriteTool.php leaks $content into metadata — audit-leak guard"
    )
    # Defensive: no 'content' key in any metadata array literal.
    assert not re.search(r"'content'\s*=>\s*\$content", src), (
        "MigrationWriteTool.php must not place $content into result metadata"
    )


# ---------- atomic write ----------


def test_atomic_write_via_rename(src: str):
    """The write is atomic: write to a temp sibling, then rename() into place
    — no half-written YAML is ever observable to the playbook."""
    assert "rename(" in src, (
        "MigrationWriteTool.php must rename() a temp file into place (atomic write)"
    )
    assert "random_bytes(" in src, (
        "MigrationWriteTool.php should use a random temp suffix to avoid collisions"
    )


# ---------- registration triangle: schema enum ↔ impl ↔ DI ----------


def test_schema_enum_has_migration_file_write():
    """The agent.schema.yaml tools[].id enum carries migration-file-write so an
    agent.yml that declares it validates."""
    if not AGENT_SCHEMA.is_file():
        pytest.skip("agent.schema.yaml missing")
    txt = AGENT_SCHEMA.read_text()
    assert "migration-file-write" in txt, (
        "agent.schema.yaml tools[].id enum missing 'migration-file-write'"
    )


def test_di_registers_write_tool():
    """common.neon registers MigrationWriteTool in the ToolRegistry factory AND
    as a service constructed with %nosRepoRoot% — so forAgent() can hand it to
    the runner."""
    if not COMMON_NEON.is_file():
        pytest.skip("common.neon missing")
    neon = COMMON_NEON.read_text()
    assert "register(@App\\AgentKit\\Tools\\MigrationWriteTool)" in neon, (
        "common.neon ToolRegistry factory does not register MigrationWriteTool"
    )
    assert "App\\AgentKit\\Tools\\MigrationWriteTool(%nosRepoRoot%)" in neon, (
        "common.neon does not construct MigrationWriteTool(%nosRepoRoot%)"
    )
    assert re.search(r"nosRepoRoot:\s*::getenv\(NOS_REPO_ROOT\)", neon), (
        "common.neon does not define nosRepoRoot from ::getenv(NOS_REPO_ROOT)"
    )


def test_migration_author_profile_has_scope_for_the_tool():
    """The migration-author dir profile already carries nos.migration.write in
    audit.capability_scopes (the overnight build provisioned it), so the tool's
    requiredScopes() ⊆ the agent's scopes and forAgent() will not throw."""
    if not MIGRATION_AUTHOR_DIR.is_file():
        pytest.skip("migration-author/agent.yml missing")
    txt = MIGRATION_AUTHOR_DIR.read_text()
    assert "nos.migration.write" in txt, (
        "migration-author/agent.yml must carry nos.migration.write in "
        "audit.capability_scopes for MigrationWriteTool to load"
    )
