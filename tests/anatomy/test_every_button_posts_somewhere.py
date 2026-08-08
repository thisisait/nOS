"""A form whose action is `#` is a button that does nothing, quietly.

WHAT WAS FOUND, 2026-08-08, while adding an Answer button to /inbox.

Nette renders an unroutable `{plink Presenter:action}` as the literal `#`
rather than raising, so a form built around it posts to the CURRENT url — a GET
render — and the operator sees the page reload with their action apparently
accepted. Measured against the running Wing:

    $ curl -s .../inbox | grep -o 'action="[^"]*"'
    action="#"
    action="#"
    action="#"

Those are the "Mark read" buttons on the A9 notification queue. `Inbox:markRead`
had no route. **Nothing has ever been marked read**, since A9 shipped in May.
There is no error, no log line, and the button looks exactly like a button.

It surfaced only because the Answer button being added would have inherited it —
and an Approve button that posts nowhere is materially worse than a Mark-read
one, because the operator believes they authorised something.

WHAT THIS GATE DOES. Every `{plink Target:action …}` and `{link …}` in a Latte
template must resolve to a route declared in RouterFactory. It is a static
check: it compares the set of link targets against the set of routed targets,
and it is deliberately blunt about the direction that matters — an unrouted
target is a dead control; a routed target nobody links is merely unused.

WHAT IT CANNOT SEE: `n:href` attributes resolved dynamically, a route present but
matching a different parameter shape, and any link built by string
concatenation. A live probe for `action="#"` is the honest complement and costs
one curl — worth running whenever a new form ships.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WING = REPO / "files/anatomy/wing"
ROUTER = WING / "app/Core/RouterFactory.php"
TEMPLATES = WING / "app/Templates"

#: Targets Nette resolves without an explicit route entry.
BUILTIN = {"this", "Homepage:default", "Error:default"}


def routed_targets() -> set[str]:
    src = ROUTER.read_text(encoding="utf-8")
    # addRoute('mask', 'Presenter:action')
    return {m.group(1) for m in re.finditer(r"addRoute\(\s*'[^']*'\s*,\s*'([^']+)'", src)}


def linked_targets() -> dict[str, set[str]]:
    """target -> the templates that link it."""
    out: dict[str, set[str]] = {}
    for tpl in TEMPLATES.rglob("*.latte"):
        src = tpl.read_text(encoding="utf-8")
        for m in re.finditer(r"\{(?:plink|link)\s+([A-Za-z][A-Za-z0-9]*:[A-Za-z][A-Za-z0-9]*)", src):
            out.setdefault(m.group(1), set()).add(str(tpl.relative_to(WING)))
    return out


def test_every_linked_action_has_a_route():
    routed = routed_targets()
    offenders = []
    for target, templates in sorted(linked_targets().items()):
        if target in BUILTIN or target in routed:
            continue
        offenders.append(f"{target}  ← {', '.join(sorted(templates))}")
    assert not offenders, (
        "template link(s) with no route in RouterFactory — Nette renders these "
        "as `action=\"#\"`, so the form posts to the current page and the "
        "action silently does not happen:\n  " + "\n  ".join(offenders)
        + "\n\nThis is how /inbox's Mark-read button did nothing from May to "
        "August 2026 without a single error."
    )


def test_the_router_declares_the_inbox_verbs():
    """Named explicitly: these two are the ones that were missing."""
    routed = routed_targets()
    for target in ("Inbox:markRead", "Inbox:answer"):
        assert target in routed, (
            f"{target} has no route. Its button will render action=\"#\" and "
            "post to a GET render."
        )


def test_state_changing_forms_are_post():
    """A GET link cannot be a decision — and requirePostMethod would reject it.

    Every presenter action reached by a form here is state-changing; a template
    that linked one with an anchor would produce a control that 405s or, worse,
    performs the change on a crawler's prefetch.
    """
    offenders = []
    for tpl in TEMPLATES.rglob("*.latte"):
        src = tpl.read_text(encoding="utf-8")
        for m in re.finditer(r"<a\b[^>]*\{plink\s+(\w+:(?:markRead|answer|approve|reject|cancel))", src):
            offenders.append(f"{tpl.relative_to(WING)}: <a> to {m.group(1)}")
    assert not offenders, (
        "state-changing action(s) linked as an anchor rather than posted:\n  "
        + "\n  ".join(offenders)
    )
