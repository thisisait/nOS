"""The face layout pin must name the graph it was frozen against.

THE MEASUREMENT (2026-08-24). The face lane's forceLayout determinism pin
(graphLayout.force.pin.json) hashes node positions computed FROM
anatomy-graph.json — so every regeneration of the graph that changes the
default view moves the hash, and the pin's own comment has always said so:
"any commit that touches anatomy-graph.json must re-freeze this pin" (the
6b960b47 lesson). It happened anyway, for the second time: three graph
regens between 2026-08-20 and 2026-08-23 (`72b909e3`, `43a6dd08`,
`669030a6`), no re-freeze, and the face CI job was red for three days with
a hash mismatch nobody connected to the graph — because the duty lives in
the vitest lane and the regen workflow runs the PYTEST lane.

This gate moves the tripwire into the lane that causes the change. The pin
records `graphSha256` — the sha256 of the anatomy-graph.json it was frozen
against — and this file compares it to the artifact. A regen without a
re-freeze now fails HERE, in the same suite that already forces the regen
itself (test_anatomy_graph_is_sound.py), with the remedy in the message.

What this gate cannot do, honestly: it cannot verify the POSITION hash —
that needs node and belongs to the vitest lane. It only proves the pin and
the graph were frozen together. Editing graphSha256 by hand without running
vitest defeats it; gates guard forgetting, not falsification.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FACE = REPO / "files" / "anatomy" / "face" / "src" / "lib" / "anatomy"
PIN = FACE / "graphLayout.force.pin.json"
GRAPH = FACE / "anatomy-graph.json"

REMEDY = (
    "anatomy-graph.json changed since the layout pin was frozen. Re-freeze "
    "deliberately: (1) cd files/anatomy/face && npx vitest run "
    "src/lib/anatomy/graphLayout.test.ts — if it fails, take the Received "
    "hash into defaultViewPositionsSha256; (2) shasum -a 256 "
    "src/lib/anatomy/anatomy-graph.json into graphSha256; (3) bump pinnedAt."
)


def test_the_pin_and_the_graph_exist():
    """Positive control — a moved file must not read as a passing bind."""
    assert PIN.is_file(), f"pin missing at {PIN}"
    assert GRAPH.is_file(), f"graph missing at {GRAPH}"


def test_the_pin_names_the_graph_it_froze():
    pin = json.loads(PIN.read_text(encoding="utf-8"))
    assert "graphSha256" in pin, (
        "the pin does not record which graph it was frozen against; "
        "without that binding a graph regen goes red only in the face lane, "
        "days later. " + REMEDY
    )
    actual = hashlib.sha256(GRAPH.read_bytes()).hexdigest()
    assert pin["graphSha256"] == actual, REMEDY


def test_the_two_graph_copies_are_one_artifact():
    """The gate hashes the face copy the test imports; this pins that the
    state/ copy is the same bytes, so 'which copy' can never be a loophole
    (tools/anatomy-graph-gen.py writes both in one call)."""
    state_copy = REPO / "state" / "anatomy-graph.json"
    assert state_copy.read_bytes() == GRAPH.read_bytes(), (
        "state/anatomy-graph.json and the face vendored copy diverge — "
        "run tools/anatomy-graph-gen.py"
    )


# ── and the file the pytest lane rewrites must survive the FACE lane ────────
#
# MEASURED 2026-08-29, one hour after the gate above did its job. The regen
# went red here, the pin was re-frozen with `json.dumps(indent=2)`, this file
# went green — and CI failed anyway, in the face lane, on `prettier --check`:
# the shell's config is `useTabs: true` and Python had written spaces.
#
# That is the SAME defect this file was written to close, one layer along: the
# duty lives in the lane that causes the change (pytest, which regenerates)
# and the complaint arrives in a different one (face, which formats). So the
# formatting half moves here too, checked the only way that is honest without
# running node — against the repo's own declared prettier options rather than
# against a remembered convention.

import json as _json


def test_the_pin_is_written_the_way_the_face_lane_will_check_it() -> None:
    prettierrc = _json.loads((FACE.parents[2] / ".prettierrc").read_text(encoding="utf-8"))
    if not prettierrc.get("useTabs"):
        return  # the shell changed its mind; prettier --check is then the only judge
    body = PIN.read_text(encoding="utf-8")
    offenders = [i + 1 for i, line in enumerate(body.splitlines())
                 if line.startswith(" ")]
    assert not offenders, (
        f"{PIN.name} is space-indented at line(s) {offenders}; the face lane runs "
        "`prettier --check` with useTabs:true and will fail. Re-freeze with "
        "`npx prettier --write` after writing it, or edit it by hand — a "
        "`json.dumps(indent=2)` re-freeze passes every gate in THIS lane and "
        "reddens the other one."
    )
    assert body.endswith("\n"), f"{PIN.name} has no trailing newline; prettier requires one"
