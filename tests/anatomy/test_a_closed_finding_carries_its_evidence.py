"""Gate — a security finding may not be closed on an assertion alone. Ratchet.

WHAT THE ROADMAP ROW ASKED FOR, AND WHY THIS IS NOT THAT. `sec-queue-authorship`
says the nightly scan overwrites what a human wrote into
`docs/llm/security/remediation-queue.json`, citing REM-144 losing its disposition
for a day on 2026-08-05. That was checked on 2026-08-22 by replaying all 75
commits that have ever touched the file and diffing `resolved_by` /
`resolved_detail` / `resolution` per row across every pair: **zero** dispositions
were ever lost. The premise did not hold, so the companion-file split it implies
would have been a schema change protecting against something that has not
happened — at the cost of teaching every reader to join two files.

REM-144's own `resolved_detail` says what actually went wrong, in its own words:
the record "carried a bare status+date until then, with no resolved_by and no
evidence". Not a loss. A claim nobody had to back, which a reader six days later
had to re-derive from scratch — on a CRITICAL.

Measured the same day: **50 of 155 closed rows carry no evidence of any kind**,
48 of them `resolved`, and among them CRITICALs on portainer, traefik and five
n8n rows. Roughly a third of everything this queue calls finished is
unfalsifiable.

WHY A RATCHET AND NOT A TARGET. Fifty rows cannot be repaired by inventing
evidence for them — the people and the runs that closed them are months gone, and
a gate demanding retroactive proof would be satisfied by fiction, which is worse
than the silence it replaces. So this pins the number where it is and lets it
only fall. The estate already chose this shape once for the same reason
(`sec-p4`, "blast-radius gate, ratchets not targets").

The reader is `tools/rem-status.py --unproven`.
"""
from __future__ import annotations

import json
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
QUEUE = REPO / "docs/llm/security/remediation-queue.json"

#: Measured 2026-08-22 at cycle 37, 212 rows. LOWER THIS when rows get their
#: evidence; never raise it. Raising it is the one edit this gate exists to make
#: someone argue for out loud.
UNPROVEN_CEILING = 50


def _items() -> list[dict]:
    raw = json.loads(QUEUE.read_text(encoding="utf-8"))
    return raw["items"] if isinstance(raw, dict) and "items" in raw else raw


def _unproven(items: list[dict]) -> list[dict]:
    """Imported shape, kept literal here on purpose.

    The reader owns the definition; this restates it rather than importing it,
    so that widening `EVIDENCE_FIELDS` in the tool cannot quietly lower the count
    this gate sees. A gate that reads its subject's own definition of passing is
    the shape CLAUDE.md refuses.
    """
    closed = ("resolved", "wontfix", "obsolete", "vendor-blocked")
    evidence = ("resolved_by", "resolution", "resolved_detail",
                "blocked_reason", "decision")
    return [i for i in items
            if i.get("status") in closed
            and not any(i.get(f) for f in evidence)]


def test_unproven_closures_never_increase() -> None:
    items = _items()
    bare = _unproven(items)
    closed = sum(1 for i in items
                 if i.get("status") in ("resolved", "wontfix", "obsolete",
                                        "vendor-blocked"))
    assert len(bare) <= UNPROVEN_CEILING, (
        f"{len(bare)} of {closed} closed rows carry no evidence; the ratchet is "
        f"{UNPROVEN_CEILING}. A row closed since the ceiling was set did not "
        f"record WHY. Add one of resolved_by / resolution / resolved_detail / "
        f"blocked_reason / decision to it — or, if you are lowering the ratchet, "
        f"lower it here too.\n  new: "
        + ", ".join(sorted(i.get("id", "?") for i in bare)[-8:])
    )


def test_the_ratchet_is_not_slack() -> None:
    """A ceiling far above the real count stops being a ratchet.

    If someone repairs forty rows and leaves the constant at fifty, the gate goes
    back to permitting forty new silent closures. Fail when the gap opens.
    """
    bare = _unproven(_items())
    assert UNPROVEN_CEILING - len(bare) <= 5, (
        f"the ratchet is {UNPROVEN_CEILING} but only {len(bare)} rows are "
        f"unproven — lower UNPROVEN_CEILING to {len(bare)}, or the gate is "
        f"quietly licensing {UNPROVEN_CEILING - len(bare)} more silent closures"
    )


def test_the_reader_can_name_them() -> None:
    """The count is useless without the list; `--unproven` is how it is read."""
    tool = (REPO / "tools/rem-status.py").read_text(encoding="utf-8")
    assert "--unproven" in tool, "the reader lost its --unproven listing"
    assert "def unproven(" in tool, "the reader lost its unproven() query"
