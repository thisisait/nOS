"""Anatomy CI gates — AgentKit multi-agent process pool (A14 follow-up,
2026-05-07).

Pins the contracts of the parallel sub-agent dispatch path:

  1. ProcessPool MUST use the ARRAY form of proc_open. String form delegates
     to /bin/sh -c on POSIX and reopens the A14.1 RCE class (same doctrine
     as BashReadOnlyTool).
  2. Concurrency cap is sliding-window with a hard ceiling of 16 — anything
     above goes to a real queue (Pulse), not in-process parallelism.
  3. Coordinator pre-creates one agent_threads row per child with
     parent_thread_uuid = primary, role='child', status='pending', so the
     audit lineage is complete BEFORE the child subprocess even starts.
  4. Coordinator NEVER edits Runner.php — Runner stays the single-agent
     contract. The multi-agent path lives entirely in Coordinator +
     ProcessPool.
  5. Coordinator timeout drains all running children via SIGTERM with a
     grace period; sibling failure is non-fatal.
  6. Schema + loader bumped max_concurrent_threads to 16 (was 10), default 4
     (was 1) to match the multi-agent baseline.

These tests do NOT execute PHP — they parse source with regex / static
inspection, which is enough for the contract assertions and runs in CI
without a PHP interpreter.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

try:
    import yaml  # noqa: F401
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False


REPO_ROOT = Path(__file__).resolve().parents[2]
WING_APP = REPO_ROOT / "files" / "anatomy" / "wing" / "app"
COORD_PHP = WING_APP / "AgentKit" / "Coordinator.php"
POOL_PHP = WING_APP / "AgentKit" / "ProcessPool.php"
RUNNER_PHP = WING_APP / "AgentKit" / "Runner.php"
LOADER_PHP = WING_APP / "AgentKit" / "AgentLoader.php"
SESSION_REPO_PHP = WING_APP / "Model" / "AgentSessionRepository.php"
RUN_AGENT_BIN = REPO_ROOT / "files" / "anatomy" / "wing" / "bin" / "run-agent.php"
SCHEMA_YAML = REPO_ROOT / "state" / "schema" / "agent.schema.yaml"


@pytest.fixture(scope="module")
def coord_src() -> str:
    if not COORD_PHP.is_file():
        pytest.skip(f"{COORD_PHP} missing")
    return COORD_PHP.read_text()


@pytest.fixture(scope="module")
def pool_src() -> str:
    if not POOL_PHP.is_file():
        pytest.skip(f"{POOL_PHP} missing")
    return POOL_PHP.read_text()


@pytest.fixture(scope="module")
def runner_src() -> str:
    if not RUNNER_PHP.is_file():
        pytest.skip(f"{RUNNER_PHP} missing")
    return RUNNER_PHP.read_text()


@pytest.fixture(scope="module")
def runner_bytes() -> bytes:
    if not RUNNER_PHP.is_file():
        pytest.skip(f"{RUNNER_PHP} missing")
    return RUNNER_PHP.read_bytes()


@pytest.fixture(scope="module")
def loader_src() -> str:
    if not LOADER_PHP.is_file():
        pytest.skip(f"{LOADER_PHP} missing")
    return LOADER_PHP.read_text()


@pytest.fixture(scope="module")
def session_repo_src() -> str:
    if not SESSION_REPO_PHP.is_file():
        pytest.skip(f"{SESSION_REPO_PHP} missing")
    return SESSION_REPO_PHP.read_text()


@pytest.fixture(scope="module")
def run_agent_src() -> str:
    if not RUN_AGENT_BIN.is_file():
        pytest.skip(f"{RUN_AGENT_BIN} missing")
    return RUN_AGENT_BIN.read_text()


# =====================================================================
# Contract 1 — proc_open array form ONLY (string form is RCE)
# =====================================================================

def test_processpool_uses_array_form_proc_open(pool_src: str) -> None:
    """ProcessPool MUST call proc_open with an argv array, never a string.

    String-form proc_open delegates to /bin/sh -c on POSIX, reopening the
    A14.1 RCE class. We mirror BashReadOnlyTool's gate here so the doctrine
    propagates to the multi-agent dispatcher.
    """
    # No `proc_open($cmd, ...)` or `proc_open("...", ...)` patterns.
    forbidden = re.search(
        r"proc_open\s*\(\s*(\$cmd\b|\$command\b|\"|')",
        pool_src,
    )
    assert forbidden is None, (
        f"ProcessPool.php uses string-form proc_open: '{forbidden.group(0)}'. "
        "String form delegates to /bin/sh -c on POSIX (RCE class A14.1). "
        "Switch to array form: proc_open([$verb, ...args], ...)"
    )
    # Must call proc_open with an argv VARIABLE that's clearly an array.
    has_array_call = bool(re.search(
        r"proc_open\s*\(\s*\$job->argv\b",
        pool_src,
    ))
    assert has_array_call, (
        "ProcessPool.php must call proc_open($job->argv, ...) — the "
        "argv ARRAY form is the only safe shape."
    )


def test_processpool_pipes_are_non_blocking(pool_src: str) -> None:
    """A chatty child can fill its 64KB stdout pipe and deadlock if the
    pool's poll loop reads in blocking mode. Non-blocking pipes are the
    structural fix."""
    assert "stream_set_blocking" in pool_src, (
        "ProcessPool.php must call stream_set_blocking($pipe, false) on "
        "stdout/stderr pipes — blocking reads deadlock chatty children."
    )
    assert re.search(r"stream_set_blocking\(\s*\$pipes\[1\]\s*,\s*false\s*\)", pool_src), (
        "stdout pipe (\\$pipes[1]) must be non-blocking."
    )
    assert re.search(r"stream_set_blocking\(\s*\$pipes\[2\]\s*,\s*false\s*\)", pool_src), (
        "stderr pipe (\\$pipes[2]) must be non-blocking."
    )


# =====================================================================
# Contract 2 — sliding-window cap with hard ceiling 16
# =====================================================================

def test_processpool_hard_cap_is_16(pool_src: str) -> None:
    """The MAX_CONCURRENCY_CAP constant pins the ceiling. Beyond 16 you
    want a real queue runner (Pulse), not in-process parallelism — locking
    this in code so a future raise gets reviewed deliberately."""
    assert re.search(
        r"MAX_CONCURRENCY_CAP\s*=\s*16\b",
        pool_src,
    ), (
        "ProcessPool.php MAX_CONCURRENCY_CAP must equal 16. Above 16 the "
        "design assumption (in-process subprocess management) breaks down."
    )


def test_processpool_clamps_concurrency(pool_src: str) -> None:
    """Constructor MUST clamp maxConcurrent into [1, 16] — never trust
    agent.yml values; old YAMLs may carry stale caps."""
    # The clamp logic should reference the cap constant.
    assert re.search(r"MAX_CONCURRENCY_CAP", pool_src), (
        "ProcessPool constructor must reference MAX_CONCURRENCY_CAP for clamping."
    )
    # And there should be a default-fallback for non-positive input.
    assert "DEFAULT_CONCURRENCY" in pool_src, (
        "ProcessPool must define DEFAULT_CONCURRENCY for the fallback path."
    )


def test_loader_max_threads_range_matches_schema(loader_src: str) -> None:
    """AgentLoader rejects max_concurrent_threads outside [1, 16] —
    matching the schema's bumped maximum. Was 1..10 in initial A14."""
    m = re.search(
        r"max_concurrent_threads must be (\d+)\.\.(\d+)",
        loader_src,
    )
    assert m is not None, (
        "AgentLoader.php no longer carries the max_concurrent_threads "
        "range error message — the validation contract is gone."
    )
    lo, hi = int(m.group(1)), int(m.group(2))
    assert (lo, hi) == (1, 16), (
        f"max_concurrent_threads range expected (1, 16); loader says ({lo}, {hi}). "
        "Schema and loader must agree."
    )


@pytest.mark.skipif(not _YAML_AVAILABLE, reason="PyYAML not installed")
def test_schema_max_concurrent_threads_capped_at_16() -> None:
    """The schema's maximum must equal the loader's cap — divergence here
    means an agent.yml that passes one validator could be rejected by the
    other, surfacing as a confusing CI red."""
    if not SCHEMA_YAML.is_file():
        pytest.skip(f"{SCHEMA_YAML} missing")
    schema = yaml.safe_load(SCHEMA_YAML.read_text())
    multiagent = schema["properties"]["multiagent"]["properties"]["max_concurrent_threads"]
    assert multiagent["maximum"] == 16, (
        f"agent.schema.yaml multiagent.max_concurrent_threads.maximum must "
        f"equal 16; got {multiagent.get('maximum')}"
    )
    assert multiagent["minimum"] == 1
    assert multiagent.get("default") == 4, (
        "Default should be 4 (A14 multi-agent baseline)."
    )


# =====================================================================
# Contract 3 — parent/child lineage in agent_threads
# =====================================================================

def test_session_repo_has_child_thread_methods(session_repo_src: str) -> None:
    """The repository surface for child threads has three required methods:
    startChildThread (status=pending), markChildThreadRunning (pending →
    running), endChildThread (running → idle/error/terminated)."""
    for method in ("startChildThread", "markChildThreadRunning", "endChildThread"):
        assert f"public function {method}(" in session_repo_src, (
            f"AgentSessionRepository.php missing {method} — "
            "the multi-agent lineage path is broken."
        )


def test_start_child_thread_requires_parent_thread_uuid(session_repo_src: str) -> None:
    """A child without a parent_thread_uuid breaks the lineage join.
    startChildThread MUST refuse the insert at the boundary."""
    assert "requires non-empty parent_thread_uuid" in session_repo_src, (
        "AgentSessionRepository::startChildThread must throw when "
        "parent_thread_uuid is empty — this is the lineage invariant."
    )
    assert "requires role=child" in session_repo_src, (
        "AgentSessionRepository::startChildThread must throw when role != child."
    )


def test_coordinator_uses_parent_thread_uuid_for_children(coord_src: str) -> None:
    """Coordinator MUST set parent_thread_uuid = its own primary thread when
    creating child rows. Without this the SELECT * FROM agent_threads WHERE
    parent_thread_uuid=? query returns nothing and the audit tree is gone."""
    assert "parent_thread_uuid" in coord_src
    assert "primaryThreadFor" in coord_src, (
        "Coordinator must look up its own primary thread to bind children."
    )
    # The startChildThread call should pass parent_thread_uuid.
    assert re.search(
        r"startChildThread\s*\(",
        coord_src,
    ), "Coordinator must call sessions->startChildThread() for each child."


def test_coordinator_emits_thread_lifecycle_events(coord_src: str) -> None:
    """Coordinator emits agent_thread_start + agent_thread_end on its OWN
    trace_id so the audit table joins coordinator → children via
    actor_action_id = coordinator_session_uuid."""
    assert "agent_thread_start" in coord_src, (
        "Coordinator must emit 'agent_thread_start' on child spawn."
    )
    assert "agent_thread_end" in coord_src, (
        "Coordinator must emit 'agent_thread_end' on child exit."
    )


# =====================================================================
# Contract 4 — Runner.php is NEVER edited by the multi-agent path
# =====================================================================

def test_runner_php_unchanged_by_multiagent_pool(runner_src: str) -> None:
    """The multi-agent path is implemented entirely in Coordinator +
    ProcessPool. Runner stays the single-agent contract — if it grows
    multi-agent code, the scope partition with the Dreams worker is
    violated and merge conflicts follow.
    """
    forbidden = ["ProcessPool", "ChildSpec", "ChildOutcome", "ChildrenRunResult"]
    for term in forbidden:
        assert term not in runner_src, (
            f"Runner.php now references '{term}' — the multi-agent path "
            "must live in Coordinator/ProcessPool, not Runner. Revert."
        )
    # The session_uuid + trace_id generation must remain Runner's contract;
    # multi-agent path doesn't override these.
    assert "TraceContext::newTraceId()" in runner_src, (
        "Runner.php still owns trace_id generation — that's the contract."
    )


def test_coordinator_does_not_extend_runner_signature(runner_src: str) -> None:
    """Runner::run() signature parameters are pinned. If a multi-agent
    refactor added a parameter, Coordinator's child-spawn path can't
    forward to it cleanly — the contract is sealed."""
    # Match `public function run(` block up to the closing `): RunResult`
    m = re.search(r"public function run\((.+?)\):\s*RunResult", runner_src, re.DOTALL)
    assert m is not None, "Runner::run() declaration not found"
    sig = m.group(1)
    # Must contain exactly these 6 parameters, in this order:
    expected = ["agentName", "userPrompt", "vaultName", "trigger", "triggerId", "actorId"]
    for name in expected:
        assert f"${name}" in sig, (
            f"Runner::run() lost parameter ${name} — multi-agent rework "
            "must NOT change the Runner surface."
        )


# =====================================================================
# Contract 5 — SIGTERM on coordinator timeout
# =====================================================================

def test_processpool_uses_sigterm_on_timeout(pool_src: str) -> None:
    """When the pool's wallclock exceeds timeoutSeconds, every running
    child receives SIGTERM (15) via posix_kill. SIGKILL (9) is reserved
    for the post-grace-period sweep so children get a chance to flush
    their final agent_session_end audit row."""
    # First posix_kill should be SIGTERM (15)
    sigterm_calls = re.findall(r"posix_kill\(\s*\$status\['pid'\]\s*,\s*15\s*\)", pool_src)
    assert len(sigterm_calls) >= 1, (
        "ProcessPool must SIGTERM (15) running children on coordinator timeout."
    )
    # And SIGKILL (9) reserved for the sweep
    sigkill_calls = re.findall(r"posix_kill\(\s*\$status\['pid'\]\s*,\s*9\s*\)", pool_src)
    assert len(sigkill_calls) >= 1, (
        "ProcessPool must have a SIGKILL (9) sweep after the SIGTERM grace period."
    )


def test_processpool_marks_pending_jobs_terminated_on_timeout(pool_src: str) -> None:
    """Pending jobs (not yet spawned when timeout hits) are also drained —
    one batch's results map MUST contain an entry for every input job."""
    assert "coordinator timeout reached before dispatch" in pool_src, (
        "ProcessPool must record pending-but-undispatched jobs as "
        "terminated when the coordinator timeout fires."
    )


# =====================================================================
# Contract 6 — sibling failure non-fatal
# =====================================================================

def test_processpool_continues_on_sibling_failure(pool_src: str) -> None:
    """A non-zero exit on one child must not abort the rest of the pool.
    The result is recorded with status='error', the loop keeps draining."""
    # The 'idle' / 'error' status branching on exitCode must exist.
    assert re.search(
        r"status:\s*\$exit\s*===\s*0\s*\?\s*'idle'\s*:\s*'error'",
        pool_src,
    ), (
        "ProcessPool must distinguish exit==0 (idle) from non-zero (error) "
        "while keeping the loop running for siblings."
    )


def test_processpool_spawn_failure_non_fatal(pool_src: str) -> None:
    """proc_open returning false (e.g. argv binary not found) must NOT
    propagate up — record the failure as one job's result and move on."""
    # The spawn() helper returns null on failure; the dispatch loop must
    # handle null gracefully (record error, continue).
    assert re.search(r"\$spawn\s*===\s*null", pool_src), (
        "ProcessPool dispatch must handle spawn() returning null — "
        "spawn failure is non-fatal at the pool level."
    )


# =====================================================================
# bin/run-agent.php contract — accepts new args, NEVER echoes secrets
# =====================================================================

def test_run_agent_bin_accepts_multiagent_args(run_agent_src: str) -> None:
    """The CLI must accept --parent-thread-uuid + --thread-uuid so the
    coordinator can spawn it as a child without losing lineage."""
    assert "parent-thread-uuid" in run_agent_src, (
        "bin/run-agent.php must accept --parent-thread-uuid"
    )
    assert "thread-uuid" in run_agent_src, (
        "bin/run-agent.php must accept --thread-uuid"
    )
    assert "$multiagentContext" in run_agent_src, (
        "bin/run-agent.php must capture the multi-agent context from argv "
        "for echo back into the exit summary."
    )


def test_run_agent_bin_never_echoes_secrets(run_agent_src: str) -> None:
    """The exit-summary JSON must never contain ANTHROPIC_API_KEY,
    BONE_SECRET, or any vault names — only identifiers. Coordinator
    only needs UUIDs to fold the lineage."""
    forbidden_in_summary = [
        "ANTHROPIC_API_KEY",
        "BONE_SECRET",
        "WING_API_TOKEN",
    ]
    # Find the summary block — between `$summary = [` and the matching `];`
    m = re.search(r"\$summary\s*=\s*\[(.+?)\];", run_agent_src, re.DOTALL)
    assert m is not None, "bin/run-agent.php has no $summary array literal"
    summary_block = m.group(1)
    for secret in forbidden_in_summary:
        assert secret not in summary_block, (
            f"bin/run-agent.php $summary leaks {secret} — never include "
            "secrets in the child's stdout summary."
        )


# =====================================================================
# Defensive — files that MUST exist
# =====================================================================

def test_coordinator_php_carries_runwithchildren() -> None:
    """The new entry point exists — without this Pulse/CLI callers can't
    invoke the parallel path."""
    src = COORD_PHP.read_text()
    assert "public function runWithChildren(" in src, (
        "Coordinator.php must declare runWithChildren() — the parallel "
        "sub-agent dispatch entry point."
    )


def test_processpool_php_exists_and_has_dispatch() -> None:
    src = POOL_PHP.read_text()
    assert "final class ProcessPool" in src
    assert "public function dispatch(" in src, (
        "ProcessPool::dispatch() is the sole public entry point — "
        "without it Coordinator can't drive the pool."
    )
