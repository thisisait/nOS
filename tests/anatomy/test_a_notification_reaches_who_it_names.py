"""`target_actor_id` is an address. Delivery must read it.

WHAT WAS FOUND, 2026-08-08, when the operator asked whether agents could mail
each other yet.

`notifications.target_actor_id` has been a real column since A9 — defaulted to
`'operator'`, filtered by `NotificationRepository::query()`, exposed as a query
parameter by `Api\\NotificationsPresenter`. And no transport read it:

    mail   -> MAIL_RECIPIENT, one fixed address for the whole estate
    ntfy   -> topic `nos-<severity>`, keyed by SEVERITY, not by recipient
    inbox  -> filtered correctly; the only one of the three

So a notification addressed to `agent:librarian` was delivered, silently, to the
operator. The intended reader never saw it and the operator received someone
else's post. An address field that invites the mistake and reports nothing is
worse than having no field.

THE RULE THIS PINS, and it is the whole of it: **an unroutable address must
FAIL, not fall back.** Falling back to the operator is the defect; it must never
be the fix. A row for an actor with no mail route keeps its NULL
`mail_dispatched_at`, retries to the attempt budget and is stamped carrying the
reason — visibly undelivered.

A TRAP THIS FILE ALSO GUARDS, because the fix nearly reintroduced the bug it
fixes: `fetch_pending()` did not SELECT `target_actor_id`. The routing code read
`$row['target_actor_id'] ?? 'operator'`, the `??` swallowed the missing column,
and every notification would have routed to the operator exactly as before —
with the new code in place and the tests written. A default that hides a missing
column is indistinguishable from a working default.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DISPATCH = REPO / "files/anatomy/wing/bin/dispatch-notifications.php"


def src() -> str:
    return DISPATCH.read_text(encoding="utf-8")


def code_only() -> str:
    s = re.sub(r"/\*.*?\*/", "", src(), flags=re.S)
    return re.sub(r"^\s*//.*$", "", s, flags=re.M)


def function_body(name: str) -> str:
    """One function, sliced to the NEXT top-level definition."""
    s = code_only()
    start = s.find(f"function {name}(")
    assert start != -1, f"{name}() is gone — re-point this gate"
    nxt = re.search(r"\nfunction \w+\(", s[start + 1:])
    body = s[start : start + 1 + nxt.start()] if nxt else s[start:]
    assert len(body) > 120, f"{name}() slice is implausibly short ({len(body)})"
    return body


def test_the_column_is_actually_selected():
    """Routing that reads an unfetched column silently routes to the default."""
    fetch = function_body("fetch_pending")
    assert "target_actor_id" in fetch, (
        "fetch_pending() does not SELECT target_actor_id, so every row arrives "
        "without it and `?? 'operator'` sends everything to the operator — the "
        "exact defect the routing was written to fix, reintroduced invisibly."
    )


def test_ntfy_routes_by_recipient_not_only_severity():
    body = function_body("ntfy_topic_for")
    assert "target_actor_id" in body, (
        "the ntfy topic no longer depends on the recipient."
    )
    assert "severity" in body, (
        "the operator's topic must stay `nos-<severity>` — that is the "
        "subscription already on the phone and the volume control the operator "
        "asked for."
    )
    deliver = function_body("deliver_ntfy")
    assert "ntfy_topic_for(" in deliver, (
        "deliver_ntfy no longer asks ntfy_topic_for() which topic to use."
    )


def test_an_unroutable_mail_target_fails_instead_of_falling_back():
    body = function_body("deliver_mail")
    assert "target_actor_id" in body, (
        "deliver_mail ignores target_actor_id again, so mail for any actor "
        "goes to the operator address."
    )
    # The failure must be a RETURNED error string — that is what mark_dispatched
    # records and what makes the row visibly undelivered.
    assert re.search(r"return\s+\"no mail route", body), (
        "an unroutable target does not return an error. Silently delivering to "
        "the operator, or silently skipping, are both the original defect."
    )
    assert "$recipient" in body, "the operator path no longer sends anywhere"


def test_the_operator_default_is_explicit_everywhere():
    """`operator` is a bare string with no vocabulary; keep the comparison one rule.

    If one transport treated `''` as operator and another did not, the same row
    would route two ways. Both call sites normalise the same way.
    """
    for fn in ("ntfy_topic_for", "deliver_mail"):
        body = function_body(fn)
        assert "'operator'" in body, f"{fn}() has no explicit operator case"
        assert "trim(" in body, (
            f"{fn}() does not trim target_actor_id, so ' operator' and "
            "'operator' would route differently."
        )
