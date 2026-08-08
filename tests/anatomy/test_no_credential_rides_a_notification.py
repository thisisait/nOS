"""A notification is a list every Tier-1 caller can read. Keep credentials out.

WHAT HAPPENED, 2026-08-08, found by adversarial review hours after it shipped.

`InboxPresenter` minted a per-question `reply_token`, correctly stored only its
SHA-256 in `agent_questions`, correctly kept it out of every `ToolResult` — and
then passed it in the notification's `metadata` array.

That array is stored verbatim as `notifications.metadata_json`, re-hydrated by
`NotificationRepository::query()` into a `metadata` field, and returned by
`GET /api/v1/notifications`. Verified against the live estate: every item comes
back carrying both `metadata` and `metadata_json`. `McpWingTool` is GET/POST
over the whole `/api/v1/*` surface with scope `wing.read`, and **conductor holds
`mcp-wing`** (`files/anatomy/agents/conductor/agent.yml`). So an agent did not
need to file a question to get a token — it could read one out of the operator's
notification list, at rest, in plaintext, and approve itself.

THE SHAPE OF THE MISTAKE is worth more than the fix. The token was hashed in its
own table with a comment explaining that "a plaintext token in a list is a
bearer credential handed to every reader of that list" — and was then written
into exactly such a list, three lines below, by the same commit. Getting the
hard part right can be what makes the easy part invisible.

WHAT THIS GATE COVERS: the notification insert path, for every caller, not just
the inbox. Any secret-shaped key riding into `metadata` is refused.

WHAT IT CANNOT COVER: a credential smuggled in `title` or `body` as free text,
or one built by string concatenation. Those are readable on the same endpoint
and equally fatal. If a future caller needs to get a secret to a human, the
answer is a delivery path that is not this table — not a cleverer key name.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WING = REPO / "files/anatomy/wing"
BONE = REPO / "files/anatomy/bone"

#: Substrings that mark a value as a credential. Deliberately broad: a false
#: positive costs one rename, a false negative costs what happened above.
SECRET_KEYS = ("reply_token", "token", "secret", "password", "api_key",
               "credential", "bearer", "passphrase", "private_key")

#: Keys that CONTAIN a secret word but name a non-secret. Each entry is an
#: explicit decision, not a convenience — anything not listed is refused.
ALLOWED = {
    "token_name",      # which token, not the token
    "tokens_input",    # LLM accounting
    "tokens_output",
    "tokens_cache_read",
}


def php_sources() -> list[Path]:
    return [p for p in WING.rglob("*.php") if "vendor" not in p.parts]


def notification_metadata_blocks(src: str) -> list[str]:
    """The `'metadata' => [ ... ]` array literals in a source file."""
    out = []
    for m in re.finditer(r"'metadata'\s*=>\s*\[", src):
        depth, i = 0, m.end() - 1
        while i < len(src):
            if src[i] == "[":
                depth += 1
            elif src[i] == "]":
                depth -= 1
                if depth == 0:
                    out.append(src[m.end():i])
                    break
            i += 1
    return out


def test_no_notification_metadata_carries_a_credential():
    offenders = []
    for path in php_sources():
        src = path.read_text(encoding="utf-8")
        if "'metadata'" not in src:
            continue
        for block in notification_metadata_blocks(src):
            for key in re.findall(r"'([A-Za-z0-9_]+)'\s*=>", block):
                if key in ALLOWED:
                    continue
                if any(s in key.lower() for s in SECRET_KEYS):
                    offenders.append(f"{path.relative_to(REPO)}: metadata['{key}']")
    assert not offenders, (
        "credential-shaped key(s) in notification metadata:\n  "
        + "\n  ".join(offenders)
        + "\n\nnotifications.metadata_json is returned verbatim by "
        "GET /api/v1/notifications to any bearer caller, including any agent "
        "holding mcp-wing. Deliver the secret by a path that is not this "
        "table; do not rename the key."
    )


def test_the_inbox_presenter_specifically_is_clean():
    """Named separately so a regression here reads as the original defect.

    SCOPED TO THE INSERT, not the file. The first draft asserted that
    `'reply_token'` appears nowhere in the code and failed immediately —
    `actionAnswer` legitimately READS `reply_token` from the request body,
    because answering is the one operation that must present it. A gate that
    cannot tell an input from an egress forbids the feature working.
    """
    src = (WING / "app/Presenters/Api/InboxPresenter.php").read_text(encoding="utf-8")
    code = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    code = re.sub(r"^\s*//.*$", "", code, flags=re.M)

    start = code.find("$this->notifications->insert(")
    assert start != -1, (
        "InboxPresenter no longer notifies on a filed question. A question "
        "nobody is told about sits open until its deadline and then decides "
        "itself."
    )
    depth, i = 0, code.find("(", start)
    while i < len(code):
        if code[i] == "(":
            depth += 1
        elif code[i] == ")":
            depth -= 1
            if depth == 0:
                break
        i += 1
    insert_call = code[start:i]
    assert "reply_token" not in insert_call, (
        "InboxPresenter passes reply_token into the notification insert. That "
        "row is returned by GET /api/v1/notifications to any bearer caller, "
        "including any agent holding mcp-wing."
    )
    # The one legitimate egress: handing the token back to whoever filed the
    # question, once, in the 201 response.
    assert "sendCreated($made)" in code, (
        "the ask() result is no longer returned to the caller that filed the "
        "question — that is the only copy anyone downstream can use."
    )


def test_the_reason_is_recorded_next_to_the_code():
    """A bare absence looks like an oversight and gets 'helpfully' filled in."""
    src = (WING / "app/Presenters/Api/InboxPresenter.php").read_text(encoding="utf-8")
    assert "metadata_json" in src and "mcp-wing" in src, (
        "InboxPresenter no longer explains why the reply token is absent from "
        "the notification. Someone will add it back as a convenience."
    )
