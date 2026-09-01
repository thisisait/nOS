"""A notification its successor retired must stop being unread IN THE FACE.

MEASURED 2026-09-01 against the live wing.db: `bin/reconcile-inbox.php` had
retired 66 rows (superseded_at set, wing_inbox_read_at deliberately NULL —
nobody read them), Wing's own badge and Bone's list both excluded them, and the
face did not: `projectNotification` mapped only `wing_inbox_read_at`, so the
menubar counted 7 high/critical alerts where 6 were live. One of the phantom
three was a CRITICAL its own successor had replaced.

WHAT THIS PINS, and why it is a source scan. The BEHAVIOUR is pinned where it
can be executed — `src/lib/anatomy/wing.test.ts` runs `projectNotification` +
`isUnreadWork` under vitest in CI. What vitest cannot see is a NEW surface
re-deriving "unread" from `.read` alone (a route handler cannot be imported
without SvelteKit's generated `./$types`). So this gate reads the face sources
with comments stripped and refuses a negated `.read` outside the one predicate
every caller must route through.
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
SRC = REPO / "files/anatomy/face/src"
WING_TS = SRC / "lib/anatomy/wing.ts"

#: `!n.read`, `!note.read`, `! n.read` — the shape that skips supersession.
NEGATED_READ = re.compile(r"!\s*[A-Za-z_$][\w$]*\.read\b")


def _strip_comments(text: str) -> str:
    """Read the CODE, never the prose about it — a comment naming `!n.read`
    would otherwise pass for the defect, and one naming the fix would hide it."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$", "", text)


def _sources() -> list[pathlib.Path]:
    return [
        p
        for p in SRC.rglob("*")
        if p.suffix in {".ts", ".svelte"} and not p.name.endswith(".test.ts")
    ]


def test_the_projection_carries_supersession() -> None:
    src = _strip_comments(WING_TS.read_text(encoding="utf-8"))
    assert "superseded_at" in src, (
        "wing.ts does not read `superseded_at` from Wing's payload — a retired "
        "row arrives with wing_inbox_read_at NULL and renders as unread work"
    )
    assert re.search(r"superseded:\s*Boolean\(\s*raw\.superseded_at", src), (
        "projectNotification must map superseded_at onto the view; without it "
        "every consumer is back to deciding unread from `.read` alone"
    )


def test_unread_work_requires_both_facts() -> None:
    src = _strip_comments(WING_TS.read_text(encoding="utf-8"))
    body = re.search(
        r"export function isUnreadWork\([^)]*\)[^{]*\{(.*?)\n\}", src, flags=re.S
    )
    assert body, "wing.ts must export isUnreadWork — the one place unread is decided"
    assert ".read" in body.group(1) and ".superseded" in body.group(1), (
        "isUnreadWork must consult BOTH: read is a claim about a human, "
        f"superseded is a claim about a successor. Body: {body.group(1)!r}"
    )


def test_no_face_surface_decides_unread_alone() -> None:
    offenders = []
    for path in _sources():
        code = _strip_comments(path.read_text(encoding="utf-8"))
        if path == WING_TS:
            # The predicate itself is the sanctioned use; anything else in this
            # file is a second answer to the same question.
            code = re.sub(
                r"export function isUnreadWork\([^)]*\)[^{]*\{.*?\n\}", "", code, flags=re.S
            )
        for hit in NEGATED_READ.finditer(code):
            offenders.append(f"{path.relative_to(REPO)}: {hit.group(0)}")
    assert not offenders, (
        "a face surface derives 'unread' from `.read` alone — a row its own "
        "successor retired would count as work forever. Use isUnreadWork():\n  "
        + "\n  ".join(offenders)
    )
