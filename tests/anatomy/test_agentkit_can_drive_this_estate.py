"""Anatomy gate: AgentKit must have a client for the backend that actually runs.

MEASURED 2026-08-11, against the live wing.db:

    SELECT model_uri, count(*) FROM agent_sessions  ->  claude-cli, 3
    SELECT count(*) FROM agent_iterations           ->  0

Three sessions for all time, every one written by the shell bridge, and the
grader/outcome loop has never run once in production. `w-agentkit-spine` states
the estate has two agent runtimes and everything asked of AgentKit — sessions,
iterations, grader decisions, vault indirection, lineage — is a property of the
one NOT running the agents.

THE REASON IS NARROWER THAN "TWO RUNTIMES", and finding it is what made the row
actionable. `Factory::fromUri` knew exactly two providers: `anthropic-*`, which
needs an `ANTHROPIC_API_KEY` this estate does not set, and `openclaw-*`, whose
gateway was dead for weeks (exit 78, fixed the same day). The eight nightly
ceremonies run on the operator's `claude` subscription through
`pulse-run-agent.sh`. AgentKit had no client that could reach it — so it was not
that the agents chose the other runtime; AgentKit could not have run them.

WHAT IS PINNED HERE. That the provider stays routable, that the adapter REFUSES
a tool schema rather than dropping one, and that it reads message content blocks
instead of casting the array. The refusal is the load-bearing part: the CLI runs
its own tool loop and returns a final message, so tools handed to it cannot be
honoured — and accepting an argument it does not read is the exact defect
`MapHandler` shipped and had to be corrected for on the same day.

WHAT THIS CANNOT DO: prove a real agent runs through it. That needs the live
estate and an operator-supervised parallel-run night, which is the rest of the
row. Shape here, effect there.
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
LLM = REPO / "files/anatomy/wing/app/AgentKit/LLMClient"
FACTORY = LLM / "Factory.php"
ADAPTER = LLM / "ClaudeCliAdapter.php"


def test_the_cli_provider_is_routable() -> None:
    src = FACTORY.read_text(encoding="utf-8")
    assert "'claude'" in src and "buildClaudeCli" in src, (
        "Factory no longer routes `claude-*` to the CLI adapter. AgentKit is "
        "back to two providers it cannot use on this machine — an API key nobody "
        "sets and a gateway that may or may not be up — which is how "
        "agent_sessions reached three rows in a year."
    )
    # The reserved providers must still throw rather than silently pick one.
    assert "not yet supported" in src, (
        "an unknown provider no longer refuses. A URI typo would fall through to "
        "whichever adapter the match happens to end on."
    )


def test_the_adapter_refuses_a_tool_schema() -> None:
    """The boundary, and it is permanent rather than pending.

    `--print` runs the CLI's own tool loop and returns one final message. A tool
    schema passed here cannot be honoured, so it must be refused — dropping it
    would make an agent believe it had tools that were never offered to anything.
    """
    src = ADAPTER.read_text(encoding="utf-8")
    body = src[src.index("public function send("):]
    body = body[: body.index("\n    /**")]
    assert re.search(r"if \(\$tools !== \[\]\)", body), (
        "ClaudeCliAdapter::send() no longer checks for a tool schema. It cannot "
        "honour one; not checking means silently dropping it."
    )
    assert "LLMPermanentError" in body, (
        "the tool refusal is not an error any more. A transient error would be "
        "retried forever against a backend that will never grow the protocol."
    )


def test_the_adapter_reads_content_blocks_not_the_array() -> None:
    """Caught by a live probe before this shipped.

    `Message::$content` is a list of blocks, not a string. The first draft cast
    it straight to a string, which PHP renders as the word "Array" — the model
    would have been asked to answer that.
    """
    src = ADAPTER.read_text(encoding="utf-8")
    assert "function textOf(" in src, (
        "the adapter no longer extracts text from content blocks. If it casts "
        "$m->content to a string again, every prompt becomes the literal word "
        "'Array' and nothing throws."
    )
    assert re.search(r"===\s*'text'", src), "textOf() no longer selects text blocks"


def test_the_adapter_does_not_build_a_shell_command() -> None:
    """A prompt is untrusted input and must never be parsed as shell syntax."""
    src = ADAPTER.read_text(encoding="utf-8")
    assert "proc_open" in src, "the adapter no longer spawns via proc_open"
    assert not re.search(r"\b(shell_exec|exec\(|system\(|passthru)\b", src), (
        "the adapter reaches for a shell. Prompts are model-authored text; a "
        "command string is how one becomes an argument list nobody intended."
    )
    # argv ARRAY form — proc_open(string) re-opens the same hole.
    assert re.search(r"proc_open\(\s*\$argv", src), (
        "proc_open is called with something other than the argv array"
    )


def test_the_shell_bridge_and_the_adapter_agree_on_the_cli_contract() -> None:
    """Two call sites, one upstream. They must not drift until one is retired.

    `pulse-run-agent.sh` discovered that `--print --output-format json` is what
    yields a usable token tally; this adapter depends on the same fact. If the
    script's flags change and the adapter's do not, the spine cutover would
    compare two runtimes that were never speaking to the same CLI.
    """
    script = (REPO / "files/anatomy/scripts/pulse-run-agent.sh").read_text(encoding="utf-8")
    adapter = ADAPTER.read_text(encoding="utf-8")
    for flag in ("--print", "--output-format", "--permission-mode"):
        assert flag in script, f"pulse-run-agent.sh no longer passes {flag}"
        assert flag in adapter, (
            f"ClaudeCliAdapter no longer passes {flag} while the shell bridge "
            "still does. The two runtimes would be driving the CLI differently, "
            "and a parallel-run comparison between them would measure the "
            "difference in flags rather than in runtimes."
        )
