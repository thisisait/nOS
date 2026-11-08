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

Since 2026-11-08 (gate-diet-freshness-one) the binding is part of
`tools/anatomy-graph-gen.py --check`, run by test_generated_files_hold.py;
`tools/regenerate.py` re-freezes. What stays here: both files exist, and the
pin is written the way the face lane's prettier will check it.
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FACE = REPO / "files" / "anatomy" / "face" / "src" / "lib" / "anatomy"
PIN = FACE / "graphLayout.force.pin.json"
GRAPH = FACE / "anatomy-graph.json"


def test_the_pin_and_the_graph_exist():
    """Positive control — a moved file must not read as a passing bind."""
    assert PIN.is_file(), f"pin missing at {PIN}"
    assert GRAPH.is_file(), f"graph missing at {GRAPH}"


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
