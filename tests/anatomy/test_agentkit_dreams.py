"""Anatomy CI gate — AgentKit Dreams (memory consolidation, post-A14, U-B-Dreams).

Pins the contract surface of the Dreams cycle:
  * agent_memory_stores table is declared with CREATE TABLE IF NOT EXISTS
  * the agent.yml schema carries the optional `dream:` block with a
    read-only tool_roster enum (mcp-wing-read / mcp-bone-read)
  * Runner.loadMemoryContext() exists and was APPENDED at end of the class
    (so multi-worker batches don't conflict on Runner.php)
  * existing Runner method signatures (run + private helpers) survive
    untouched — no signature drift from U-B-Dreams' work
  * the Dreamer structurally refuses tool invocation (empty tool list to
    the LLM, plus an explicit refusal branch on tool_use blocks)
  * the dream-agent.php CLI honours the documented exit codes
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_EXT = REPO_ROOT / "files" / "anatomy" / "wing" / "db" / "schema-extensions.sql"
AGENT_SCHEMA = REPO_ROOT / "state" / "schema" / "agent.schema.yaml"
RUNNER = REPO_ROOT / "files" / "anatomy" / "wing" / "app" / "AgentKit" / "Runner.php"
DREAMER = REPO_ROOT / "files" / "anatomy" / "wing" / "app" / "AgentKit" / "Memory" / "Dreamer.php"
MEMORY_STORE = REPO_ROOT / "files" / "anatomy" / "wing" / "app" / "AgentKit" / "Memory" / "MemoryStore.php"
MEMORY_REPO = REPO_ROOT / "files" / "anatomy" / "wing" / "app" / "Model" / "AgentMemoryStoreRepository.php"
DREAM_CLI = REPO_ROOT / "files" / "anatomy" / "wing" / "bin" / "dream-agent.php"
COMMON_NEON = REPO_ROOT / "files" / "anatomy" / "wing" / "app" / "config" / "common.neon"


def test_agent_memory_stores_table_declared_idempotent():
    """The new table MUST use CREATE TABLE IF NOT EXISTS — schema-extensions.sql
    is loaded by init-db.php on every run, so a fresh `CREATE TABLE` would
    fail on the second run. Belt-and-suspenders: the contract requires it,
    and init-db's idempotent reload depends on it."""
    sql = SCHEMA_EXT.read_text()
    # Match across whitespace.
    assert re.search(
        r"CREATE TABLE IF NOT EXISTS\s+agent_memory_stores\b",
        sql, re.IGNORECASE,
    ), "schema-extensions.sql missing CREATE TABLE IF NOT EXISTS agent_memory_stores"
    # Required columns the Dreamer + repo + tests assume.
    for col in ("uuid", "agent_name", "title", "content",
                "source_session_uuid", "trace_id",
                "created_at", "updated_at"):
        assert re.search(
            rf"\b{re.escape(col)}\b", sql,
        ), f"agent_memory_stores missing column {col}"
    # Indexes the repo's listRecent / countForAgent paths assume.
    assert re.search(
        r"CREATE INDEX IF NOT EXISTS\s+idx_memory_agent_name\b",
        sql, re.IGNORECASE,
    ), "agent_memory_stores missing idx_memory_agent_name index"
    assert re.search(
        r"CREATE INDEX IF NOT EXISTS\s+idx_memory_updated\b",
        sql, re.IGNORECASE,
    ), "agent_memory_stores missing idx_memory_updated index"


def test_agent_schema_declares_optional_dream_block():
    """state/schema/agent.schema.yaml grew a `dream:` block with the read-only
    tool roster enum. Pinning this so a refactor that drops the block fails
    CI before agents that already opt in start failing validation."""
    src = AGENT_SCHEMA.read_text()
    assert "dream:" in src, "agent.schema.yaml lost the `dream:` block"
    # The tool_roster enum MUST be a strict subset of read-only ids — adding
    # bash-* or mcp-wing (write-capable) here would be a doctrine violation.
    # Match the enum block specifically inside `tool_roster`.
    m = re.search(
        r"tool_roster:.*?enum:\s*((?:\s*-\s*[a-z0-9-]+\s*)+)",
        src, re.DOTALL,
    )
    assert m, "dream.tool_roster has no enum block"
    enum_block = m.group(1)
    items = re.findall(r"-\s*([a-z0-9-]+)", enum_block)
    assert sorted(items) == ["mcp-bone-read", "mcp-wing-read"], (
        f"dream.tool_roster enum drifted: {items} — must be the read-only "
        "subset {mcp-wing-read, mcp-bone-read}"
    )
    # No bash or write-capable ids may appear ANYWHERE inside the dream block.
    dream_block_match = re.search(
        r"^\s*dream:.*?(?=^\s{0,2}\w)", src,
        re.DOTALL | re.MULTILINE,
    )
    if dream_block_match:
        dream_src = dream_block_match.group(0)
        for forbidden in ("bash-read-only", "bash-write", "mcp-wing\n",
                          "mcp-bone\n"):
            # Tightened: explicit-list check. The non-read variants of the
            # tools must not surface inside dream:.
            assert forbidden not in dream_src, (
                f"dream block leaked a write-capable tool id: {forbidden!r}"
            )


def test_runner_load_memory_context_appended_at_end_of_class():
    """Contract: loadMemoryContext() was added at the end of the Runner class
    so U-B-MA's potential edits higher in the file don't trivially conflict
    with U-B-Dreams. Verify the method exists AND that no class member
    appears between it and the closing `}` of the class."""
    src = RUNNER.read_text()
    # Find the method.
    m = re.search(
        r"public function loadMemoryContext\([^)]*\)\s*:\s*array",
        src,
    )
    assert m, "Runner.php is missing public function loadMemoryContext(): array"
    # Find the END of the Runner class. The Runner class is followed by the
    # RunResult class — the boundary is the `}` immediately preceding the
    # `final class RunResult` line.
    runresult_idx = src.find("final class RunResult")
    assert runresult_idx > 0, "Runner.php must still declare RunResult after Runner"
    runner_class_end = src.rfind("}", 0, runresult_idx)
    assert runner_class_end > m.start(), (
        "loadMemoryContext() must live inside Runner class (before RunResult)"
    )
    # No NEW public function may exist between loadMemoryContext and the
    # closing brace — keeps the "appended at end" discipline mechanically
    # checkable.
    tail = src[m.start():runner_class_end]
    other_methods = re.findall(
        r"public function (\w+)\(", tail,
    )
    # The only method in this slice should be loadMemoryContext itself.
    assert other_methods == ["loadMemoryContext"], (
        f"loadMemoryContext is no longer the LAST member of Runner: also found "
        f"{other_methods[1:]}. Append-at-end discipline broken."
    )


def test_runner_run_signature_unchanged():
    """U-B-Dreams contract: run() signature is locked. Pin its exact named-
    argument list so any drift surfaces immediately. The constructor may grow
    a new optional dep at the end (memoryStore is allowed); the run() method
    body may NOT change its public surface.

    Baseline shape includes the U-B-UI `sessionUuid` parameter added 2026-05-07
    so the operator-trigger HTTP path can pre-allocate the UUID before child boot.
    """
    src = RUNNER.read_text()
    m = re.search(
        r"public function run\(\s*string \$agentName,\s*"
        r"\?string \$userPrompt = null,\s*"
        r"\?string \$vaultName = null,\s*"
        r"string \$trigger = 'operator',\s*"
        r"\?string \$triggerId = null,\s*"
        r"\?string \$actorId = null,\s*"
        r"\?string \$sessionUuid = null,\s*\)\s*:\s*RunResult",
        src, re.MULTILINE,
    )
    assert m, (
        "Runner::run() signature drifted. Expected the locked shape "
        "(agentName, userPrompt, vaultName, trigger, triggerId, actorId, sessionUuid): RunResult"
    )


def test_runner_private_helpers_unchanged():
    """Pin the existing private helper signatures so accidental edits surface."""
    src = RUNNER.read_text()
    for needle in (
        "private function runToolUseLoop(",
        "private function runOutcomeLoop(",
        "private function callWithRetry(",
        "private function summariseConversation(",
        "private function defaultPrompt(",
    ):
        assert needle in src, (
            f"Runner.php private helper '{needle.rstrip('(')}' is missing — "
            "U-B-Dreams contract forbids touching existing helpers"
        )


def test_dreamer_enforces_no_tool_invocation():
    """Tool restriction enforcement (the contract's keystone): the Dreamer
    MUST issue the LLM call with an EMPTY tool list (structural read-only
    enforcement) AND MUST refuse any tool_use blocks the LLM emits anyway.
    Without these two guards the dream cycle could escape its read-only
    promise. The roster declared in agent.yml is also recorded in audit
    for forensic clarity."""
    src = DREAMER.read_text()
    # Guard 1: empty tool list passed to send().
    # `$llm->send($systemPrompt, $messages, [], 4096)` — the [] is the tools arg.
    assert re.search(
        r"\$llm->send\([^,]+,\s*\$messages,\s*\[\]\s*,",
        src,
    ), "Dreamer must call $llm->send(...) with [] as the tools argument"
    # Guard 2: refusal branch on tool_use blocks.
    assert "toolUseBlocks() !== []" in src, (
        "Dreamer must refuse responses that contain tool_use blocks "
        "(read-only enforcement)"
    )
    assert "tool_use_refused" in src, (
        "Dreamer must emit an audit event with stop_reason=tool_use_refused "
        "when the LLM tries to invoke a tool during a dream cycle"
    )
    # Doctrine: bash + write endpoints must not appear ANYWHERE in the
    # Dreamer source — the dream cycle is read-only.
    for forbidden in ("bash-read-only", "bash-write",
                      "BashReadOnlyTool", "McpWingWriteTool"):
        assert forbidden not in src, (
            f"Dreamer.php references a non-readonly capability: {forbidden!r}"
        )


def test_dreamer_telemetry_redacts_full_content():
    """Memory entries are not secrets but DO carry operator-note-grade context.
    The contract bans logging full content. Verify the Dreamer emits redacted
    payloads (uuid/title/length) and never embeds raw entry content in audit
    payloads."""
    memory_src = MEMORY_STORE.read_text()
    # The MemoryStore must expose a redactForTelemetry() helper.
    assert "redactForTelemetry" in memory_src, (
        "MemoryStore must expose redactForTelemetry() so audit emission "
        "is grep-able + uniform"
    )
    # That helper must build a (uuid, title, length) triple — never include
    # 'content' in the output array. Static check.
    redact_match = re.search(
        r"redactForTelemetry.*?return \$out;",
        memory_src, re.DOTALL,
    )
    assert redact_match, "redactForTelemetry must return a built-up array"
    redact_body = redact_match.group(0)
    assert "'content'" not in redact_body, (
        "redactForTelemetry must NOT include 'content' in its output — "
        "memory entries are operator-note-grade text"
    )
    for needed in ("'uuid'", "'title'", "'length'"):
        assert needed in redact_body, (
            f"redactForTelemetry output is missing key {needed}"
        )


def test_dream_cli_exit_codes_documented_and_used():
    """The CLI doc-comment promises 0/1/2 semantics; verify the script's
    actual exit calls match. exit(2) for config errors, exit(1) for runtime
    errors, exit(0) on success."""
    src = DREAM_CLI.read_text()
    # Must declare the three exit codes in the doc-comment.
    for code, description in [
        ("0", "cycle completed"),
        ("1", "dream error"),
        ("2", "configuration error"),
    ]:
        assert re.search(
            rf"\*\s+{code}\s+{description}", src,
        ), f"dream-agent.php doc-comment missing exit code {code} — {description}"
    # Must call exit(0), exit(1), and exit(2) in the right places.
    assert "exit(0);" in src, "dream-agent.php missing exit(0)"
    assert "exit(1);" in src, "dream-agent.php missing exit(1)"
    assert "exit(2);" in src, "dream-agent.php missing exit(2)"
    # exit(2) should be the path for missing --agent + bad numeric args.
    assert re.search(
        r"empty\(\$opts\['agent'\]\).*?exit\(2\)",
        src, re.DOTALL,
    ), "dream-agent.php must exit(2) when --agent is missing"


def test_dreamer_di_wired_and_uses_existing_factory():
    """Belt-and-suspenders: common.neon registers the new services so the CLI
    container resolves them without hand-wiring. Also pins that we did NOT
    introduce a new LLM factory — Dreamer reuses App\\AgentKit\\LLMClient\\Factory
    (no new composer deps allowed)."""
    neon = COMMON_NEON.read_text()
    assert "App\\Model\\AgentMemoryStoreRepository" in neon, (
        "common.neon must register AgentMemoryStoreRepository"
    )
    assert "App\\AgentKit\\Memory\\MemoryStore" in neon, (
        "common.neon must register App\\AgentKit\\Memory\\MemoryStore"
    )
    assert "App\\AgentKit\\Memory\\Dreamer" in neon, (
        "common.neon must register App\\AgentKit\\Memory\\Dreamer"
    )
    dreamer_src = DREAMER.read_text()
    assert "use App\\AgentKit\\LLMClient\\Factory as LLMFactory" in dreamer_src, (
        "Dreamer must reuse the existing LLMClient\\Factory — the contract "
        "forbids new composer deps for a new LLM client surface"
    )
