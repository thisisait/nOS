"""The Anatomy view observes the estate. It must not be able to change it.

WHY A GATE RATHER THAN A CONVENTION. "Read-only" is the kind of property that is
true on the day it is written and quietly false three commits later, when
someone adds a pause button because the data was right there. The blast radius
of a mistake in this app is the whole scheduled-job layer — emergency-halt,
pause, run-trigger all exist in Wing and all are one fetch away — so the
property is worth pinning at the shape level rather than trusting to review.

TWO HALVES, because there are two ways to lose it:

  1. THE BFF ROUTE exports only GET. SvelteKit answers 405 for a verb with no
     exported handler, so the absence of `export const POST` is not a stylistic
     preference — it is the enforcement.

  2. THE PROJECTION withholds the fields that must never reach a browser. This
     is the half that is not about writes at all: `GET /api/v1/pulse_jobs`
     returns each job's env block verbatim, which on 2026-08-05 was 57 live
     credential values across 23 of 25 jobs — Bone's HMAC secret, the Wing API
     token, agent client secrets, the MariaDB root password. A route that
     forwarded the upstream response unchanged would publish all of it to every
     browser that opens the app.

Retro-red: verified by adding `export const POST` to the route (red on the first
half) and by spreading the raw job into the projection's return (red on the
second, and on four of the vitest cases besides).

The projection's own behaviour — states, staleness, sorting — is pinned by
`files/anatomy/face/src/lib/anatomy/pulse.test.ts`, which runs in vitest where
it can execute the code. This gate checks only the two structural properties,
which is all a static reader can honestly claim.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
ROUTE = REPO / "files/anatomy/face/src/routes/bff/pulse/+server.ts"
PROJECTION = REPO / "files/anatomy/face/src/lib/anatomy/pulse.ts"
UPSTREAM = REPO / "files/anatomy/face/src/lib/server/upstream.ts"

WRITE_VERBS = ["POST", "PUT", "PATCH", "DELETE"]

# Upstream field names that carry credentials or host layout. The projection
# names these itself in WITHHELD_UPSTREAM_FIELDS; this list is the independent
# copy, on purpose — a gate that imported the value it checks would pass for
# any value at all.
WITHHELD = ["env_json", "args_json"]


def _route() -> str:
    return ROUTE.read_text(encoding="utf-8")


def test_the_route_exists():
    """Positive control — a missing file must not read as a passing gate."""
    assert ROUTE.is_file(), (
        "files/anatomy/face/src/routes/bff/pulse/+server.ts is gone. Either the "
        "Anatomy view was removed, or it moved and this gate is now blind."
    )
    assert PROJECTION.is_file(), "the Pulse projection module is gone"


@pytest.mark.parametrize("verb", WRITE_VERBS)
def test_the_bff_route_exports_no_write_handler(verb):
    assert not re.search(rf"^\s*export\s+const\s+{verb}\b", _route(), re.MULTILINE), (
        f"the Pulse BFF route exports a {verb} handler. The Anatomy view is an "
        f"observability surface over the scheduled-job layer, where pause, "
        f"emergency-halt and run-trigger all exist upstream — a write path here "
        f"puts them one fetch from a browser. Actions belong in Wing UI, which "
        f"already has the tier gates."
    )


def test_the_bff_route_exports_a_read_handler():
    """Otherwise the check above passes vacuously against a dead file."""
    assert re.search(r"^\s*export\s+const\s+GET\b", _route(), re.MULTILINE), (
        "the route exports no GET either — it answers 405 to everything, so the "
        "no-write assertions above prove nothing about a working surface"
    )


@pytest.mark.parametrize("field", WITHHELD)
def test_the_projection_never_emits_a_credential_bearing_field(field):
    """The field may be READ from upstream; it may not be EMITTED.

    So this looks at the returned object literal, not the whole file — the
    module has to mention `env_json` to explain why it refuses it, and a gate
    that fired on the explanation would be noise.
    """
    src = PROJECTION.read_text(encoding="utf-8")
    emitted = re.search(rf"^\s*{field}\s*[:,]", src, re.MULTILINE)
    assert not emitted, (
        f"the Pulse projection emits `{field}`. Upstream returns it verbatim "
        f"and it carries live credentials — 57 of them across 23 jobs when this "
        f"was measured. The projection is the only thing between that and a "
        f"browser's devtools."
    )


def test_the_projection_spreads_nothing_from_upstream():
    """A spread is how an allow-list silently becomes a proxy.

    `...raw` in the return object re-admits every upstream field including the
    ones above, and it does so invisibly — the field names never appear in the
    diff. This is the mutation the retro-red used.
    """
    src = PROJECTION.read_text(encoding="utf-8")
    for spread in re.findall(r"\.\.\.\(?\s*(raw|summary)\b", src):
        pytest.fail(
            f"the projection spreads `{spread}` into its output. That converts "
            f"the allow-list into a proxy without naming a single field, which "
            f"is exactly how this defect would arrive unnoticed."
        )


def test_the_wing_token_stays_server_side():
    """`$lib/server/*` is the SvelteKit boundary; the check is that we use it."""
    assert "NOS_WING_API_TOKEN" in UPSTREAM.read_text(encoding="utf-8"), (
        "the Wing API token is no longer read in $lib/server/upstream.ts — if it "
        "moved somewhere importable from client code, SvelteKit will happily "
        "bundle it into the browser"
    )
    face_src = REPO / "files/anatomy/face/src"
    for path in face_src.rglob("*.svelte"):
        assert "NOS_WING_API_TOKEN" not in path.read_text(encoding="utf-8"), (
            f"{path.relative_to(REPO)} references the Wing API token. A component "
            f"is client code; the token must never leave $lib/server/."
        )
