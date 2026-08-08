"""An approval an agent can grant itself is decoration, not a gate.

THE PROPERTY. `agent_questions.reply_token` authorises answering exactly one
question. `AgentQuestionRepository::ask()` returns it in plaintext exactly once;
`InboxPresenter` hands that copy straight to the notification, which carries it
to a human. If the token ever reached the MODEL — in a ToolResult, in a log
line, in an error message — the agent would hold the credential that approves
its own request, and every `ask_operator` call would be a formality.

WHY IT NEEDED A DEDICATED TOOL rather than `mcp_wing`. `McpWingTool` is
GET/POST over the whole `/api/v1/*` surface and returns up to 16 KiB of the
response body verbatim. `POST /api/v1/inbox/questions` legitimately answers with
`{uuid, reply_token}` — so an agent holding `mcp-wing` can file a question and
read its own token out of the response. That is not hypothetical: it is what
would have happened if `ask_operator` had been a prompt convention instead of a
tool. `AskOperatorTool` talks to the repository directly and drops the token.

WHAT THIS FILE CANNOT DO, said plainly so a green run is not over-read: it
cannot stop an agent that has been GIVEN `mcp-wing` from calling the inbox
endpoint itself. That is a capability-scope decision in each `agent.yml`, not a
code path — the last test here states the exposure rather than pretending to
close it.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TOOL = REPO / "files/anatomy/wing/app/AgentKit/Tools/AskOperatorTool.php"
PRESENTER = REPO / "files/anatomy/wing/app/Presenters/Api/InboxPresenter.php"
NEON = REPO / "files/anatomy/wing/app/config/common.neon"


def tool_src() -> str:
    return TOOL.read_text(encoding="utf-8")


def execute_body() -> str:
    src = tool_src()
    return src[src.find("public function execute") :]


def test_the_token_never_enters_a_tool_result():
    """No ToolResult may carry the reply token, by any route."""
    body = execute_body()
    results = re.findall(r"ToolResult::(?:ok|error)\((.*?)\);", body, re.S)
    assert results, "no ToolResult returns found — has execute() been rewritten?"
    for r in results:
        assert "reply_token" not in r, (
            "a ToolResult mentions reply_token. The model must never receive "
            "the credential that answers its own question — an agent that can "
            "approve itself has not been gated, it has been decorated."
        )
    # $made holds the token; returning the whole array would leak it wholesale.
    assert not re.search(r"ToolResult::ok\(\s*\$made", body), (
        "execute() returns the raw ask() result, which contains reply_token."
    )


def test_the_token_is_explicitly_discarded():
    """Not merely unused — dropped, on purpose, where a reader will see it."""
    body = execute_body()
    assert "unset($made)" in body, (
        "AskOperatorTool does not explicitly discard the ask() result holding "
        "the reply token. 'We happen not to use it' decays into 'we used it' "
        "the first time someone adds a debug line; the discard is the record "
        "of the decision."
    )


def code_only(php: str) -> str:
    """PHP with comments removed.

    The first version of the test below searched the whole file for
    `/api/v1/inbox` and failed on the docblock that EXPLAINS why the tool does
    not use it. A gate that cannot tell an explanation from an implementation
    punishes the documentation the estate keeps asking for.
    """
    php = re.sub(r"/\*.*?\*/", "", php, flags=re.S)
    php = re.sub(r"^\s*//.*$", "", php, flags=re.M)
    return php


def test_the_tool_does_not_reach_the_inbox_over_http():
    """Direct repository call, not mcp_wing — the response body carries the token."""
    src = tool_src()
    assert "AgentQuestionRepository" in src, (
        "AskOperatorTool no longer depends on the repository directly."
    )
    code = code_only(src)
    for over_http in ("/api/v1/inbox", "McpWingTool", "HttpClient"):
        assert over_http not in code, (
            f"AskOperatorTool CODE references `{over_http}`. Going through the "
            "HTTP endpoint puts the reply token in a response body the model "
            "can read. The tool exists precisely to avoid that."
        )


def test_pending_is_stated_to_be_neither_yes_nor_no():
    """The misreading that would make this tool dangerous.

    'Nobody answered yet' has two plausible completions — proceed, or refuse —
    and both are wrong. The result must say so in words, because the model
    reads words, not intentions.
    """
    body = execute_body()
    pending = body[body.rfind("PENDING") :]
    assert "NOT approval" in pending and "NOT refusal" in pending, (
        "the PENDING ToolResult no longer says that pending is neither "
        "approval nor refusal. An LLM will otherwise pick one."
    )
    schema = tool_src()
    assert "PENDING" in schema[: schema.find("public function execute")], (
        "the tool DESCRIPTION does not warn about PENDING. The description is "
        "what the model reads before deciding to call the tool at all."
    )


def test_the_wait_cannot_outlive_the_run():
    """A long inline wait does not suspend a run — it gets the run killed.

    A Pulse-triggered session carries max_runtime_s (default 300) after which
    the daemon SIGKILLs it, losing the session, its context and its audit
    trail, while the question sits open with nobody aware the asker is gone.
    """
    src = tool_src()
    m = re.search(r"MAX_WAIT_SECONDS\s*=\s*(\d+)", src)
    assert m, "AskOperatorTool no longer declares MAX_WAIT_SECONDS"
    assert int(m.group(1)) <= 120, (
        f"MAX_WAIT_SECONDS is {m.group(1)}s. The default Pulse runtime budget "
        "is 300 s and the wait is only one part of a turn."
    )
    assert "min(self::MAX_WAIT_SECONDS" in src, (
        "the caller-supplied wait_seconds is not clamped to MAX_WAIT_SECONDS — "
        "the constant then documents a limit nothing enforces."
    )


def test_the_tool_is_registered_and_scoped():
    neon = NEON.read_text(encoding="utf-8")
    assert "register(@App\\AgentKit\\Tools\\AskOperatorTool)" in neon, (
        "AskOperatorTool is not registered in the ToolRegistry factory — an "
        "agent declaring it would fail at session start."
    )
    assert "App\\Model\\AgentQuestionRepository" in neon, (
        "AgentQuestionRepository is not a registered service, so neither the "
        "tool nor InboxPresenter can be autowired."
    )
    src = tool_src()
    scopes = src[src.find("public function requiredScopes") :][:300]
    assert "inbox.ask" in scopes, (
        "the tool declares no inbox-specific scope, so any agent with generic "
        "mcp.tool_use could ask questions in an operator's name."
    )


def test_the_mcp_wing_exposure_is_recorded_not_hidden():
    """State what is still open rather than implying it is closed.

    Nothing here prevents an agent that has been given `mcp-wing` from POSTing
    to the inbox endpoint and reading its own token. That is a per-agent
    capability decision. A gate that quietly ignored it would read as coverage.
    """
    src = tool_src()
    assert "mcp_wing" in src or "mcp-wing" in src, (
        "AskOperatorTool's docblock no longer records that mcp_wing can reach "
        "the same endpoint and read the token. The exposure did not go away "
        "because the note did."
    )
