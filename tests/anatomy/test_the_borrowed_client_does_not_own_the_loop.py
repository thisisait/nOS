"""`dg/ai-access` is a transport. It must never become the loop.

DECIDED in `docs/idea/16-orchestrator-question.md` §5 and SPIKED live on
2026-08-18 against `api.minimax.io/anthropic`, three round trips, ~600 tokens:

    round 1  stop=tool_use   roll({"sides":20})  id=call_function_618cgpmwtio4_1
    round 2  stop=end_turn   "You rolled a **17**!"      (stateless replay held)
    round 3  stop=end_turn   toolCalls=0                 (tools withheld)

That settles what doc 16 §5 listed as unestablished: the per-instance binding
works on BOTH dialects the estate's backends speak — `OpenAICompatible\\Client`
takes `baseUrl` as a constructor argument, and `Claude\\Client` takes it through
`setOptions(customBaseUrl:)`, which is what reaches MiniMax's Anthropic-dialect
endpoint. A single-dialect adapter would have covered one of the two armed
backends.

WHAT THIS GATE PROTECTS, and it is one thing.

`Chat::setToolLoop()` makes the library execute tool calls itself. Turning it
on is a one-line change, it is the ergonomic path, it deletes code, and it
would move tool execution — and with it every `agent_tool_use` /
`agent_tool_result` audit row and the pre-spend session-ceiling check — inside
a library's loop. Doc 16 §2 is explicit that the audit welding is what the
estate IS, as against the commodity plumbing it is happy to borrow. This is the
line between the two, and it is invisible in a diff: the automatic mode looks
like a simplification.

The other half is the handler argument on `Chat\\Tool`. Passing a closure there
achieves the same thing per-tool, quietly, without the word "loop" appearing
anywhere.

WHAT THIS GATE DOES NOT CLAIM: that the adapter is wired in. It is a spike —
`Factory` still builds the hand-written adapters, and doc 16 decision 1's freeze
stands until a real ceremony runs on this. Retiring the three HTTP adapters is a
separate commit and wants its own evidence.
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
ADAPTER = REPO / "files/anatomy/wing/app/AgentKit/LLMClient/AiAccessAdapter.php"
COMPOSER = REPO / "files/anatomy/wing/composer.json"


def _src() -> str:
    return ADAPTER.read_text(encoding="utf-8")


def _code() -> str:
    """Source with comments stripped.

    The adapter's own class note explains at length why `setToolLoop` must
    never be called, so a whole-file search for that name fails on the
    documentation warning against it. A gate that its own subject's warning
    trips is a gate someone deletes rather than reads — the same trap this
    estate hit in `tools/red-status.py`'s gate a few hours earlier.
    """
    src = ADAPTER.read_text(encoding="utf-8")
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)   # block + docblock
    src = re.sub(r"//[^\n]*", "", src)                 # line comments
    return src


def test_the_adapter_this_gate_describes_exists():
    """Positive control — a deleted spike makes every check below vacuous."""
    assert ADAPTER.is_file(), (
        "AiAccessAdapter.php is gone. If the spike was abandoned, delete this "
        "gate in the same commit and say so in docs/idea/16 §5 — a passing "
        "gate over a missing file is worse than no gate."
    )
    assert "implements LLMClientInterface" in _src(), (
        "the adapter no longer implements the estate's two-method contract, "
        "which is the whole reason its blast radius is one class."
    )


def test_the_library_never_drives_the_tool_round_trip():
    src = _code()
    assert "setToolLoop" not in src, (
        "AiAccessAdapter calls Chat::setToolLoop(). That hands tool EXECUTION "
        "to the library — and with it the agent_tool_use / agent_tool_result "
        "audit rows and the ceiling check that must happen BEFORE the spend. "
        "The round trip stays in Runner; see docs/idea/16 §5."
    )
    assert not re.search(r"handler\s*:", src), (
        "a Chat\\Tool is being constructed with a `handler:` closure. That is "
        "setToolLoop by another name, one tool at a time: the library calls "
        "the closure itself, so execution leaves our loop without the word "
        "'loop' appearing in the diff."
    )


def test_both_dialects_are_reachable():
    """The estate's two armed backends do not speak the same wire protocol —
    `minimax` binds an Anthropic-dialect URL, `mistral` an OpenAI one. An
    adapter that quietly loses one of them would look fine until the other
    agent ran."""
    src = _src()
    assert "DIALECT_ANTHROPIC" in src and "DIALECT_OPENAI" in src, (
        "the adapter no longer distinguishes wire dialects; one of the two "
        "armed backends in state/llm-backends.yml would be unreachable."
    )
    assert "customBaseUrl" in src, (
        "the Anthropic-dialect path no longer sets a custom base URL, so it "
        "would call api.anthropic.com with a MiniMax key."
    )


def test_an_unreadable_finish_reason_is_not_read_as_success():
    """The exact defect the Runner was fixed for on the same day: a stop
    reason nobody set, meaning 'the model finished'."""
    src = _src()
    match = re.search(r"FinishReason::Unknown\s*=>\s*'([a-z_]+)'", src)
    assert match, "the Unknown finish reason is no longer mapped explicitly"
    assert match.group(1) != "end_turn", (
        "FinishReason::Unknown maps to 'end_turn'. A provider whose answer we "
        "could not read would be recorded as one that said it was done."
    )


def test_the_dependency_is_declared_and_carries_no_tree():
    """Zero transitive dependencies is half of why this was chosen over a
    framework: the security machine gains one row, not a subtree."""
    import json

    manifest = json.loads(COMPOSER.read_text(encoding="utf-8"))
    assert "ai-access/ai-access" in manifest.get("require", {}), (
        "AiAccessAdapter.php exists but composer.json does not require the "
        "library — the class would fatal at autoload on a fresh converge."
    )
    lock = json.loads((REPO / "files/anatomy/wing/composer.lock").read_text(encoding="utf-8"))
    pkg = next((p for p in lock["packages"] if p["name"] == "ai-access/ai-access"), None)
    assert pkg is not None, "ai-access is required but not locked"
    deps = {k for k in (pkg.get("require") or {}) if not k.startswith(("php", "ext-"))}
    assert deps == set(), (
        f"ai-access now pulls {sorted(deps)}. It was chosen partly because it "
        "pulled nothing; a transitive tree changes that trade and should be a "
        "decision, not a lockfile side effect."
    )
