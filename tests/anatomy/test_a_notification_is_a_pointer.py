"""A notification says that something happened. It never says what.

THE INVARIANT, decided 2026-08-08 when ntfy's forward-auth gate was removed so a
phone could subscribe:

    A NOTIFICATION IS A POINTER, NOT A PAYLOAD.

Everything downstream rests on it. The estate now publishes to a service whose
subscribe path is authenticated by ntfy itself rather than by Authentik, and the
credential lives on a phone — a device that gets lost, backed up to a cloud, and
handed to a repair shop. The whole safety argument for that arrangement is that
a stolen subscribe credential buys a list of "something happened" and never the
something.

That is not a hope. It is only true while nothing sensitive is put in a title, a
body, or a metadata field, and this file is what keeps it true.

WHY IT IS NOT THEORETICAL. Twelve hours before this was written, the agent-inbox
put a live `reply_token` into notification metadata — a credential that answers
an operator's approval question — and the same commit hashed that token at rest
one file away, with a comment explaining that a plaintext token in a readable
list is a bearer credential handed to every reader. Getting the hard part right
is what made the easy part invisible. An adversarial reviewer found it; four
gates written that morning did not.

WHAT THIS COVERS
  * every `metadata` array literal reaching NotificationRepository::insert
  * the ntfy delivery path, which must not learn to send new fields
  * the exposure decision itself: if ntfy ever returns to forward-auth, this
    file's premise changes and its docstring must be re-read, so the mode is
    asserted here rather than assumed

WHAT IT CANNOT COVER: a secret pasted into a `body` as free text, or built by
concatenation. Those are readable by the same subscriber. If a caller needs to
get a secret to a human, the answer is a delivery path that is not a
notification — never a cleverer field name.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
WING = REPO / "files/anatomy/wing"
DISPATCH = WING / "bin/dispatch-notifications.php"
TRAEFIK_VARS = REPO / "roles/pazny.traefik/vars/main.yml"

#: Substrings that mark a value as a credential or as personal data.
SENSITIVE = ("token", "secret", "password", "passwd", "api_key", "apikey",
             "credential", "bearer", "private_key", "session", "cookie",
             "otp", "passphrase")

#: Keys containing a sensitive word that name something harmless. Every entry
#: is a decision; anything absent is refused.
ALLOWED = {
    "token_name",        # which token, never its value
    "tokens_input",      # LLM accounting
    "tokens_output",
    "tokens_cache_read",
    "session_uuid",      # an opaque id — the lineage key, not a session cookie
    "agent_session_id",
}


def metadata_blocks(src: str) -> list[str]:
    """`'metadata' => [ ... ]` array literals, balanced-bracket scanned."""
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


def test_no_notification_metadata_names_a_secret():
    offenders = []
    for path in WING.rglob("*.php"):
        if "vendor" in path.parts:
            continue
        src = path.read_text(encoding="utf-8")
        if "'metadata'" not in src:
            continue
        for block in metadata_blocks(src):
            for key in re.findall(r"'([A-Za-z0-9_]+)'\s*=>", block):
                if key in ALLOWED:
                    continue
                if any(s in key.lower() for s in SENSITIVE):
                    offenders.append(f"{path.relative_to(REPO)}: metadata['{key}']")
    assert not offenders, (
        "sensitive key(s) in notification metadata:\n  " + "\n  ".join(offenders)
        + "\n\nA notification is a POINTER. Its subscribers now include a phone "
        "authenticated by ntfy rather than by Authentik; a leaked subscribe "
        "credential must cost a list of 'something happened' and never the "
        "something. Send an id, and let the reader fetch the detail through a "
        "path that authenticates them."
    )


def test_the_ntfy_body_is_the_notification_body_and_nothing_more():
    """The transport must not start attaching fields of its own."""
    src = DISPATCH.read_text(encoding="utf-8")
    # Slice to the NEXT function definition, whatever it is. The first draft
    # sliced to `function deliver_mail`, which sits AFTER deliver_ntfy in the
    # file — so the range ran backwards, `fn` was the empty string, and the
    # assertion below failed for a reason that had nothing to do with the code
    # under test. An empty haystack is the quiet way a search-based gate stops
    # meaning anything; here it happened to fail loudly, which was luck.
    start = src.find("function deliver_ntfy")
    assert start != -1, "deliver_ntfy is gone — this gate needs re-pointing"
    nxt = re.search(r"\nfunction \w+", src[start + 1:])
    fn = src[start : start + 1 + nxt.start()] if nxt else src[start:]
    assert len(fn) > 200, f"deliver_ntfy slice is implausibly short ({len(fn)} chars)"
    assert re.search(r"CURLOPT_POSTFIELDS\s*=>\s*\(string\) \(\$row\['body'\] \?\? ''\)", fn), (
        "deliver_ntfy no longer posts exactly the notification body. Whatever "
        "it posts now goes to every subscriber of that topic — check it against "
        "this file's invariant before widening it."
    )
    headers = re.findall(r"\$headers\[\]\s*=\s*'([A-Za-z-]+):", fn)
    headers += re.findall(r"'([A-Za-z-]+): '", fn)
    unexpected = {h for h in headers} - {"Title", "Priority", "Tags", "Click",
                                         "Authorization"}
    assert not unexpected, (
        f"deliver_ntfy sends unexpected header(s): {sorted(unexpected)}. Every "
        "header reaches every subscriber; add it to this list only after "
        "deciding it is safe to leak."
    )


def test_ntfy_is_not_forward_auth_and_that_is_why_this_file_exists():
    """The premise, asserted rather than assumed.

    If ntfy returns to `proxy`, browsers are gated by Authentik again, a phone
    can no longer subscribe at all, and the reasoning above changes. Better to
    fail here and have someone re-read it than to keep enforcing a rule whose
    justification has quietly moved.
    """
    modes = yaml.safe_load(TRAEFIK_VARS.read_text(encoding="utf-8"))["traefik_auth_modes"]
    assert modes.get("ntfy") == "none", (
        f"ntfy's edge auth mode is {modes.get('ntfy')!r}, not 'none'. This gate "
        "exists because a push client cannot complete an Authentik browser flow "
        "and ntfy authenticates subscribers itself. If that changed, re-read "
        "this file's docstring before relaxing anything."
    )


def test_ntfy_authenticates_for_itself():
    """`none` at the edge is only defensible while ntfy has real auth."""
    tpl = (REPO / "roles/pazny.ntfy/templates/server.yml.j2").read_text(encoding="utf-8")
    assert re.search(r"^\s*auth-file:", tpl, re.M), (
        "ntfy has no auth-file, so `auth-default-access` enforces NOTHING — and "
        "the edge gate has just been removed. That combination is an open "
        "notification feed. This is exactly the state measured on 2026-08-08: "
        "anonymous publish AND subscribe both returned 200."
    )
    assert "deny-all" in tpl, (
        "ntfy no longer defaults to deny-all while the edge is ungated."
    )
