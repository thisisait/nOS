"""A question notification carries a link to the surface that can answer it.

TWO DEFECTS THIS GATE PINS, found reviewing the agents-inbox completion plan
(2026-08-08):

1. THE FLAGSHIP ASK PATH NEVER NOTIFIED ANYONE. The notification insert lived
   only in `Api\\InboxPresenter::actionQuestions` — the HTTP path. But
   `AskOperatorTool`, the path a real agent actually uses, talks to
   `AgentQuestionRepository` directly (deliberately, so the reply token never
   rides an HTTP response an mcp-wing holder can read) and the repository
   inserted no notification. A tool-asked question reached no phone and no
   mailbox; it sat open until its deadline and then decided itself — the exact
   failure the presenter's own comment called "not optional". The insert
   therefore lives in `AgentQuestionRepository::ask()`, the one place both ask
   paths share.

2. THE NOTIFICATION WAS A DEAD END. `deliver_ntfy` has supported a `Click`
   header via `metadata.click_url` since A9, and nothing ever set it: the
   operator's phone said "Agent asks" with no way to act. The click target is
   `<WING_PUBLIC_URL>/inbox` — a LINK, never a credential. The reader
   authenticates at /inbox (Authentik forward-auth, Tier-1 — answering
   authorises an agent, so the deciding surface stays gated; that is a
   decision, not an oversight). The reply token must never appear in the URL:
   a click URL lands in notifications.metadata_json, in ntfy's server cache
   and in the phone's notification history.

Every assertion below reads CODE with comments stripped, scoped to the
smallest syntactic unit — four gates for this feature failed against correct
code by matching their own prose.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WING = REPO / "files/anatomy/wing"
REPOSITORY = WING / "app/Model/AgentQuestionRepository.php"
API_PRESENTER = WING / "app/Presenters/Api/InboxPresenter.php"
TOOL = WING / "app/AgentKit/Tools/AskOperatorTool.php"
PLIST = REPO / "roles/pazny.wing/templates/wing.plist.j2"
ENVFILE = REPO / "roles/pazny.wing/templates/wing.env.j2"


def code_only(src: str) -> str:
    """PHP source with block and line comments removed."""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"^\s*//.*$", "", src, flags=re.M)


def ask_body() -> str:
    code = code_only(REPOSITORY.read_text(encoding="utf-8"))
    start = code.find("public function ask(")
    end = code.find("public function answer(")
    assert start != -1 and end != -1 and start < end, (
        "AgentQuestionRepository::ask() body not locatable — the method moved; "
        "re-point this gate rather than letting it pass vacuously."
    )
    return code[start:end]


def test_the_ask_path_itself_notifies():
    """Both ask paths (HTTP and AskOperatorTool) must notify from ONE place.

    The repository is the only code both share. If this insert leaves ask(),
    the tool path goes back to filing questions nobody is told about.
    """
    assert "$this->notifications->insert(" in ask_body(), (
        "AgentQuestionRepository::ask() no longer inserts the notification. "
        "AskOperatorTool calls the repository directly — with the insert at a "
        "call site, a tool-asked question reaches no phone and no mailbox and "
        "decides itself at the deadline."
    )


def test_the_click_url_points_at_the_inbox_and_names_no_secret():
    body = ask_body()
    m = re.search(r"'click_url'\s*=>\s*([^\n]+)", body)
    assert m, (
        "the question notification no longer carries metadata.click_url — "
        "deliver_ntfy reads exactly that key for its Click header, and a "
        "notification without it is a dead end on a phone."
    )
    expr = m.group(1)
    assert "'/inbox'" in expr, (
        f"click_url no longer targets /inbox: {expr!r}. The link must land on "
        "a surface that authenticates the reader."
    )
    for forbidden in ("$token", "reply", "$uuid", "question"):
        assert forbidden not in expr, (
            f"click_url expression contains {forbidden!r}: {expr!r}. The URL "
            "lands in metadata_json, ntfy's cache and the phone's history — "
            "it must carry no credential and no per-question addressing."
        )
    assert "null" in expr, (
        f"click_url has no explicit empty-env branch: {expr!r}. With "
        "WING_PUBLIC_URL unset the value must be null (no Click header), "
        "never a fabricated URL."
    )


def test_the_public_url_is_provisioned_on_both_platforms():
    """WING_PUBLIC_URL must reach the daemon env on macOS (plist) AND Linux
    (systemd wing.env), or the click_url silently vanishes on one platform."""
    plist = PLIST.read_text(encoding="utf-8")
    assert re.search(
        r"<key>WING_PUBLIC_URL</key>\s*<string>https://\{\{ wing_domain \}\}</string>",
        plist,
    ), "wing.plist.j2 does not provision WING_PUBLIC_URL=https://{{ wing_domain }}"
    env = ENVFILE.read_text(encoding="utf-8")
    assert re.search(
        r"^WING_PUBLIC_URL=https://\{\{ wing_domain \}\}$", env, re.M
    ), "wing.env.j2 does not provision WING_PUBLIC_URL=https://{{ wing_domain }}"


def test_the_api_presenter_does_not_double_notify():
    """One insert, one place. A second insert at the HTTP call site would mean
    an HTTP-filed question notifies twice while the tool path notifies once —
    two sounds for one event, and a maintainer 'fixing' the duplicate could
    remove the shared one."""
    code = code_only(API_PRESENTER.read_text(encoding="utf-8"))
    assert "$this->notifications->insert(" not in code, (
        "Api\\InboxPresenter inserts its own notification again — the insert "
        "lives in AgentQuestionRepository::ask() so BOTH ask paths notify "
        "exactly once."
    )


def test_the_tool_path_still_never_sees_the_token():
    """Moving the notification into the repository must not have widened what
    the tool returns: the ask() result reaching AskOperatorTool still carries
    the token, and the tool must still discard it before any ToolResult."""
    code = code_only(TOOL.read_text(encoding="utf-8"))
    assert "unset($made)" in code, (
        "AskOperatorTool no longer discards the ask() result holding the "
        "reply token before building a ToolResult."
    )
