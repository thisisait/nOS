"""A journey run without its configuration must say so, not accuse the estate.

MEASURED 2026-08-13. `python3 -m pytest tests` reported:

    FAILED test_smoke.py  — e2e_journey_start row not found; pipe is broken
    FAILED test_halt_resume.py

Neither pipe was broken. `WING_EVENTS_HMAC_SECRET` was absent, so the
fire-and-forget signed POST was rejected at the door and the row the assertion
looked for never existed. The same two journeys pass under
`tools/run-journeys.sh`, which resolves those values from the estate — 10/10,
the same minute.

The cost of the old behaviour is not a red mark; it is the sentence "pipe is
broken", which sends a reader into Bone and Wing after a defect that is not
there. A test may not report a fault in the system it is pointed at when the
fault is that nobody pointed it.

WHY SKIPPING IS HONEST HERE, and only here. A skip that hides a switched-off
test is exactly what this estate has been bitten by (`test_operator_login` skipped
on every run anyone ever did, for a year, because NOS_HOST was unset). What makes
it safe now is that the sanctioned runner REFUSES to call such a skip a pass:
`tools/run-journeys.sh --strict` (the default) exits non-zero when a skip reason
names one of these variables. So bare pytest gets a pointer, the runner gets a
verdict, and neither gets a fabrication.
"""

from __future__ import annotations

import os

import pytest

#: Values `tools/run-journeys.sh` resolves from the estate. A journey needs the
#: secrets to authenticate and the host to address the right tenant; without
#: them it is not under-configured, it is un-configured.
REQUIRED = (
    "NOS_HOST",
    "WING_API_TOKEN",
    "WING_EDGE_TOKEN",
    "WING_EVENTS_HMAC_SECRET",
    "BONE_SECRET",
)


@pytest.fixture(autouse=True)
def _journeys_are_configured() -> None:
    missing = [name for name in REQUIRED if not os.environ.get(name)]
    if missing:
        pytest.skip(
            "journey not configured: "
            + ", ".join(missing)
            + " unset. Run `tools/run-journeys.sh`, which resolves these from "
            "the estate and refuses to call this skip a pass."
        )
