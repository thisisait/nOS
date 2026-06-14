"""Anatomy CI gate — every agent.yml must declare an exit_code_semantics block,
and that block must agree with the agent's system prompt about whether it emits
the NOS_AGENT_EXIT sentinel (agent-exit-code-semantics, 2026-06-14).

WHY THIS EXISTS
---------------
pulse-run-agent.sh defines a fixed trichotomy and maps it to A9 notification
severity:

    exit 0    — success, no notification
    exit 1    — actionable findings → HIGH-severity notification
    exit 2+   — environment / auth / Wing error → CRITICAL notification

Before this gate the contract was documented inconsistently: only
upgrade-advisor and upgrade-architect (the review-capable agents) told the model
to emit the `NOS_AGENT_EXIT: 1` sentinel that the runner lifts into the process
exit. Conductor / remediator / scout / inspektor / librarian said nothing, so an
operator seeing a HIGH notification couldn't tell "awaiting your review" from an
outright failure, and a future review-capable agent could silently ship without
a sentinel (always exit 0 → no notification ever fires).

This gate pins the per-agent exit contract into agent.yml itself:
  * exit_code_semantics is present with exit_0 / exit_1 / exit_2 strings.
  * emits_sentinel must agree with the system prompt — an agent whose system.md
    instructs `NOS_AGENT_EXIT` MUST declare emits_sentinel: true (else the
    runner would ignore a verdict the prompt asked for), and vice-versa.
  * a sentinel-emitting agent's exit_1 text must frame exit 1 as
    operator-review (not a crash) so the doctrine stays legible.

The JSON-Schema gate in test_agent_schema.py enforces the *shape* (required
keys, minLength). This file enforces the *cross-file consistency* between the
agent.yml block and the system prompt the runner actually reads.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENTS_DIR = REPO_ROOT / "files" / "anatomy" / "agents"

# Substrings that, in an exit_1 string, signal "operator-review, not a failure".
_REVIEW_MARKERS = ("review", "pending", "approval", "decision", "queued", "drafted")


def _all_agent_yml_paths() -> list[tuple[str, Path]]:
    if not AGENTS_DIR.is_dir():
        return []
    out = []
    for entry in sorted(AGENTS_DIR.iterdir()):
        agent_yml = entry / "agent.yml"
        if entry.is_dir() and agent_yml.is_file():
            out.append((entry.name, agent_yml))
    return out


@pytest.fixture(scope="module")
def agent_paths():
    paths = _all_agent_yml_paths()
    if not paths:
        pytest.skip(f"no agents under {AGENTS_DIR}")
    return paths


def _load(path: Path) -> dict:
    with open(path) as fh:
        return yaml.safe_load(fh)


def _system_prompt_emits_sentinel(name: str, path: Path, data: dict) -> bool:
    sp = data.get("system_prompt_path")
    if not sp:
        return False
    sp_file = path.parent / sp
    if not sp_file.is_file():
        return False
    return "NOS_AGENT_EXIT" in sp_file.read_text()


def test_every_agent_declares_exit_code_semantics(agent_paths):
    """No agent ships without an explicit exit contract — the A9 notification
    severity it can trigger must be documented, not assumed."""
    missing = []
    for name, path in agent_paths:
        ecs = _load(path).get("exit_code_semantics")
        if not isinstance(ecs, dict):
            missing.append(name)
    assert not missing, (
        "agents missing an exit_code_semantics block: " + ", ".join(missing)
    )


def test_exit_code_semantics_has_all_three_codes(agent_paths):
    """Every block documents exit 0, 1 and 2 — the full runner trichotomy."""
    failures = []
    for name, path in agent_paths:
        ecs = _load(path).get("exit_code_semantics") or {}
        for key in ("exit_0", "exit_1", "exit_2"):
            val = ecs.get(key)
            if not isinstance(val, str) or len(val.strip()) < 8:
                failures.append(f"{name}.{key}")
    assert not failures, (
        "exit_code_semantics entries missing or too short: " + ", ".join(failures)
    )


def test_emits_sentinel_matches_system_prompt(agent_paths):
    """emits_sentinel in agent.yml must agree with the system prompt the runner
    actually reads. A prompt that instructs NOS_AGENT_EXIT with emits_sentinel:
    false (or the reverse) is a silent contract drift — the runner would either
    ignore a verdict the prompt asked for, or the catalog would advertise an
    exit-1 path that never fires."""
    mismatches = []
    for name, path in agent_paths:
        data = _load(path)
        declared = bool((data.get("exit_code_semantics") or {}).get("emits_sentinel", False))
        actual = _system_prompt_emits_sentinel(name, path, data)
        if declared != actual:
            mismatches.append(
                f"{name}: emits_sentinel={declared} but system prompt "
                f"{'emits' if actual else 'does not emit'} NOS_AGENT_EXIT"
            )
    assert not mismatches, "exit-sentinel contract drift:\n  - " + "\n  - ".join(mismatches)


def test_review_capable_exit1_framed_as_review(agent_paths):
    """For agents that DO emit the sentinel, exit_1 must read as operator-review
    (queued / pending / drafted / requires a decision) — never bare 'failure'.
    This is the whole point of the finding: a HIGH notification on exit 1 must
    tell the operator it is awaiting their action, not that something broke."""
    failures = []
    for name, path in agent_paths:
        data = _load(path)
        ecs = data.get("exit_code_semantics") or {}
        if not bool(ecs.get("emits_sentinel", False)):
            continue
        exit_1 = (ecs.get("exit_1") or "").lower()
        if not any(marker in exit_1 for marker in _REVIEW_MARKERS):
            failures.append(
                f"{name}: exit_1 must frame exit 1 as operator-review "
                f"(one of {_REVIEW_MARKERS}); got: {ecs.get('exit_1')!r}"
            )
    assert not failures, "review-capable exit_1 not framed as review:\n  - " + "\n  - ".join(failures)
