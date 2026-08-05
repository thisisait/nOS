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
FACE = REPO / "files/anatomy/face/src"
# All three Anatomy BFF routes, not just the first one written. A gate that
# covers one of three views is a gate that will be true on the day the second
# is added and false on the day after.
ROUTES = [
    FACE / "routes/bff/pulse/+server.ts",
    FACE / "routes/bff/wing/+server.ts",
    FACE / "routes/bff/bone/+server.ts",
]
ROUTE = ROUTES[0]
PROJECTION = FACE / "lib/anatomy/pulse.ts"
PROJECTIONS = [
    FACE / "lib/anatomy/pulse.ts",
    FACE / "lib/anatomy/wing.ts",
    FACE / "lib/anatomy/bone.ts",
]
VIEWS = sorted((FACE / "lib/apps/native/anatomy").glob("*.svelte"))
UPSTREAM = FACE / "lib/server/upstream.ts"

WRITE_VERBS = ["POST", "PUT", "PATCH", "DELETE"]

# Upstream field names that carry credentials or host layout. The projection
# names these itself in WITHHELD_UPSTREAM_FIELDS; this list is the independent
# copy, on purpose — a gate that imported the value it checks would pass for
# any value at all.
WITHHELD = ["env_json", "args_json"]


def test_the_routes_exist():
    """Positive control — a missing file must not read as a passing gate."""
    for r in ROUTES:
        assert r.is_file(), (
            f"{r.relative_to(REPO)} is gone. Either that Anatomy view was "
            f"removed, or it moved and this gate is now blind to it."
        )
    for p in PROJECTIONS:
        assert p.is_file(), f"{p.relative_to(REPO)} is gone"


@pytest.mark.parametrize(
    "route,verb",
    [(r, v) for r in ROUTES for v in WRITE_VERBS],
    ids=lambda x: x.parent.name if isinstance(x, Path) else x,
)
def test_no_anatomy_bff_route_exports_a_write_handler(route, verb):
    src = route.read_text(encoding="utf-8")
    assert not re.search(rf"^\s*export\s+const\s+{verb}\b", src, re.MULTILINE), (
        f"{route.parent.name} exports a {verb} handler. The Anatomy views are an "
        f"observability surface over the scheduled-job layer, where pause, "
        f"emergency-halt and run-trigger all exist upstream — a write path here "
        f"puts them one fetch from a browser. Actions belong in Wing UI, which "
        f"already has the tier gates."
    )


@pytest.mark.parametrize("route", ROUTES, ids=lambda p: p.parent.name)
def test_every_anatomy_route_exports_a_read_handler(route):
    """Otherwise the check above passes vacuously against a dead file."""
    src = route.read_text(encoding="utf-8")
    assert re.search(r"^\s*export\s+const\s+GET\b", src, re.MULTILINE), (
        f"{route.parent.name} exports no GET either — it answers 405 to "
        f"everything, so the no-write assertions prove nothing about a working "
        f"surface"
    )


@pytest.mark.parametrize("route", ROUTES, ids=lambda p: p.parent.name)
def test_every_anatomy_route_gates_on_the_admin_tier(route):
    """Read-only bounds the blast radius of a bug, not the sensitivity of the
    answer. Schedules, failure output and which jobs never ran are
    administrator information regardless of the verb used to fetch them."""
    src = route.read_text(encoding="utf-8")
    assert "canViewAnatomy" in src, (
        f"{route.parent.name} does not call canViewAnatomy(). Every Anatomy "
        f"route must gate on the edge-trusted identity — and on the same helper, "
        f"so the tier cannot drift apart across three views."
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


@pytest.mark.parametrize("projection", PROJECTIONS, ids=lambda p: p.stem)
def test_no_projection_spreads_anything_from_upstream(projection):
    """A spread is how an allow-list silently becomes a proxy.

    `...raw` in the return object re-admits every upstream field including the
    ones above, and it does so invisibly — the field names never appear in the
    diff. This is the mutation the retro-red used.
    """
    src = projection.read_text(encoding="utf-8")
    for spread in re.findall(r"\.\.\.\(?\s*(raw|summary|h|e|n)\b", src):
        pytest.fail(
            f"{projection.name} spreads `{spread}` into its output. That "
            f"converts the allow-list into a proxy without naming a single "
            f"field, which is exactly how this defect would arrive unnoticed."
        )


# ── The shared UI vocabulary ────────────────────────────────────────────────
#
# Measured 2026-08-05, before it existed: 51 hand-written colour rules across
# 18 components, no shared severity type, and the same three states spelled
# four different ways. The primitives fixed that; these two checks keep it
# fixed, because a shared component is only shared while people use it.

UI = FACE / "lib/components/ui"

# Local status markup a view must not hand-roll. `.muted` is not on the list:
# it is legitimate typography for secondary text, and forbidding it would be
# forbidding a colour rather than a duplicated concept.
LOCAL_STATUS = re.compile(r'class="(note|bad|err|empty|unwired)"')


@pytest.mark.parametrize("view", VIEWS, ids=lambda p: p.stem)
def test_anatomy_views_use_the_shared_status_component(view):
    src = view.read_text(encoding="utf-8")
    hit = LOCAL_STATUS.search(src)
    assert not hit, (
        f"{view.name} hand-rolls a status class ({hit.group(1)!r}) instead of "
        f"using <StatusNote>. That is how the shell ended up with four spellings "
        f"of 'nothing here' — and why an unreachable API and an empty list "
        f"looked identical."
    )


def test_the_ui_primitives_are_present_and_small():
    """Small on purpose. A shared layer that grows without a bar becomes a
    component library nobody wants to maintain — the rule in index.ts is that
    something earns a place after three divergent copies exist."""
    assert UI.is_dir(), "$lib/components/ui is gone; the shared vocabulary went with it"
    components = sorted(p.name for p in UI.glob("*.svelte"))
    assert components, "no primitives at all — this gate is checking an empty directory"
    assert len(components) <= 8, (
        f"the primitives layer has grown to {len(components)} components "
        f"({components}). That is a component library, not a shared vocabulary; "
        f"re-read index.ts's bar before adding another."
    )


def test_the_wing_token_stays_server_side():
    """`$lib/server/*` is the SvelteKit boundary; the check is that we use it."""
    assert "NOS_WING_API_TOKEN" in UPSTREAM.read_text(encoding="utf-8"), (
        "the Wing API token is no longer read in $lib/server/upstream.ts — if it "
        "moved somewhere importable from client code, SvelteKit will happily "
        "bundle it into the browser"
    )
    # READING the variable, not naming it. The first version of this check
    # forbade the string anywhere in a .svelte file and immediately tripped on
    # StatusNote's own usage example, where the name appears in a doc comment
    # demonstrating how to say "this token is not set". A variable's NAME is
    # not its value, and a gate that cannot tell them apart will be muted by
    # whoever hits it next.
    reads_env = re.compile(r"(?:process\.)?env\s*[.\[]\s*['\"]?NOS_WING_API_TOKEN")
    for path in FACE.rglob("*.svelte"):
        hit = reads_env.search(path.read_text(encoding="utf-8"))
        assert not hit, (
            f"{path.relative_to(REPO)} reads the Wing API token from the "
            f"environment. A component is client code; the token must be read "
            f"only in $lib/server/, which SvelteKit refuses to bundle."
        )
