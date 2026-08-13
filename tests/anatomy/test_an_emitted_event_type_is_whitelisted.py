"""Every event type the code EMITS must exist in both whitelists.

WHY DERIVED AND NOT LISTED. The estate already had a twin-parity rule — Wing's
`EventRepository::VALID_TYPES` and Bone's `events.py::VALID_TYPES` must agree,
because a type present on one side only makes a Bone-proxied replay 400 with no
clue which side is short — and it is checked by roughly a dozen assertions in
`test_devlog_event_types.py`. Each of those names its types by hand.

MEASURED 2026-08-13: `agent_model_fallback` was emitted by `Runner.php` and
appeared in NEITHER list, and every parity assertion stayed green, because
parity held — both halves were equally short. `agent_binding_disarmed` landed
the same day with the same gap, by precedent. A check that compares two
artefacts to each other is blind to both being wrong together; the same shape
as the audit-chain verifier that compared the chain to itself and reported
`ok: true` for fifteen days under a retired key.

So this gate takes its question from the code that emits, and its answer from
the two lists. A new event type is covered on the day it is emitted rather than
on the day someone remembers to add an assertion for it.

SCOPE, honestly bounded. It reads `type:` arguments of `AuditEmitter::emit()`
calls that are STRING LITERALS. A type assembled at runtime (`"agent_" . $x`)
is invisible here and always will be — that is a reason not to assemble event
type names, and the sweep count below is the guard against the extractor
quietly matching nothing at all.
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
WING_APP = REPO / "files/anatomy/wing/app"
WING_LIST = WING_APP / "Model/EventRepository.php"
BONE_LIST = REPO / "files/anatomy/bone/events.py"

#: `$this->audit->emit(type: 'x', …)` and `emit('x', …)`, literal only.
EMIT_NAMED = re.compile(r"->emit\(\s*type:\s*'([a-z][a-z0-9_]+)'")
EMIT_POSITIONAL = re.compile(r"->emit\(\s*'([a-z][a-z0-9_]+)'")


def _emitted_types() -> dict[str, set[str]]:
    """type -> the files that emit it."""
    found: dict[str, set[str]] = {}
    for php in sorted(WING_APP.rglob("*.php")):
        if php == WING_LIST:
            continue
        text = php.read_text(encoding="utf-8", errors="replace")
        for pattern in (EMIT_NAMED, EMIT_POSITIONAL):
            for match in pattern.finditer(text):
                found.setdefault(match.group(1), set()).add(
                    str(php.relative_to(REPO))
                )
    return found


def _whitelist(path: pathlib.Path) -> set[str]:
    """Quoted names inside the VALID_TYPES literal.

    COMMENTS ARE STRIPPED BEFORE THE TERMINATOR IS LOCATED, and the order is
    the whole trick. Slicing first read Bone's list as 29 names instead of 77:
    the first `}` after `VALID_TYPES` is inside a comment documenting a payload
    shape — `result_json: {subject, dsar_id, …}` — so the slice ended a third
    of the way through. Both lists are heavily commented by design, so a reader
    that respects the comments only after cutting will always cut early.
    """
    text = path.read_text(encoding="utf-8")
    stripped = "\n".join(
        line.split("//")[0].split("#")[0] for line in text.splitlines()
    )
    start = stripped.index("VALID_TYPES")
    closer = "]" if path.suffix == ".php" else "}"
    end = stripped.index(closer, start)
    return set(re.findall(r"['\"]([a-z][a-z0-9_]+)['\"]", stripped[start:end]))


def test_the_extractor_finds_emitters_at_all():
    """Positive control. Zero matches would make every check below vacuous —
    which is exactly the failure mode this file was written about."""
    emitted = _emitted_types()
    assert len(emitted) >= 12, (
        f"only {len(emitted)} emitted event type(s) found; the extractor has "
        "stopped matching `->emit(type: '…')` and this gate now proves nothing. "
        "Measured 2026-08-13: 14 distinct literal types across 21 call sites."
    )
    assert "agent_session_start" in emitted, "the canonical emitter is not seen"


def test_the_whitelists_are_readable():
    """Second positive control: an empty list would satisfy nothing correctly."""
    for path in (WING_LIST, BONE_LIST):
        names = _whitelist(path)
        assert len(names) >= 60, (
            f"{path.relative_to(REPO)} yielded only {len(names)} type(s); the "
            "VALID_TYPES extractor is reading the wrong region. Measured "
            "2026-08-13: Wing 76, Bone 77 — a much smaller number means the "
            "slice ended at a brace inside a comment again."
        )


def test_every_emitted_type_is_in_wings_whitelist():
    allowed = _whitelist(WING_LIST)
    offenders = {
        t: sorted(where) for t, where in _emitted_types().items() if t not in allowed
    }
    assert not offenders, (
        "event type(s) emitted but absent from Wing's EventRepository::"
        "VALID_TYPES:\n  "
        + "\n  ".join(f"{t} — emitted by {', '.join(w)}" for t, w in offenders.items())
    )


def test_every_emitted_type_is_in_bones_whitelist():
    """The twin. A type Wing accepts and Bone does not 400s on replay, and the
    400 names neither the type nor the side that is short."""
    allowed = _whitelist(BONE_LIST)
    offenders = {
        t: sorted(where) for t, where in _emitted_types().items() if t not in allowed
    }
    assert not offenders, (
        "event type(s) emitted but absent from Bone's VALID_TYPES:\n  "
        + "\n  ".join(f"{t} — emitted by {', '.join(w)}" for t, w in offenders.items())
    )
