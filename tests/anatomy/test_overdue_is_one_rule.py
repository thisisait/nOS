"""A job that stopped firing must not render calm — and both surfaces must agree.

THE BLIND SPOT, closed 2026-08-07. Wing's job-health classifier
(`app/Presenters/PulsePresenter.php`) was a `match (true)` over
broken / stuck / failing / paused / never with `default => 'ok'` — and NO
staleness arm. A job that ran cleanly every night for a fortnight and then
stopped forever keeps `bad=0`, `unfinished=0`, `last_exit=0`, `paused=0` and a
non-null `last_fired_at`. It fell through to `ok`, and the page sorts `ok`
last, so it printed at the bottom of the screen with its last successful
timestamp beside it.

WHY next_fire_at IS THE SIGNAL: Wing advances it only when a run FINISHES
(`PulseRepository::recordFinish`). A Pulse daemon that stopped therefore leaves
every job's scheduled time frozen in the past — which makes staleness the one
detector that catches a dead scheduler, as opposed to a failing job.

MEASURED WHILE THE GAP WAS STILL OPEN: `keap:keap-features-sync` exited
255 / 255 / 3 on three consecutive nights (2026-07-25..27) — with run rows and
with non-zero exits — and nothing in the estate reacted. A silent STOP is
strictly quieter than that, and it was invisible by construction.

THE POINT OF THIS FILE IS THE AGREEMENT, not the arm. The face had `overdue`
from 2026-08-05 (`files/anatomy/face/src/lib/anatomy/pulse.ts`) while its own
backend disagreed — two surfaces over one database, one of them lying, and
nothing comparing them. That is this estate's signature defect, so the rule is
now compared rather than merely present:

  * the grace window formula must be identical on both sides;
  * paused must suppress overdue on both sides;
  * neither may treat a missing schedule as late.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WING = REPO / "files/anatomy/wing/app/Presenters/PulsePresenter.php"
FACE = REPO / "files/anatomy/face/src/lib/anatomy/pulse.ts"
TEMPLATE = REPO / "files/anatomy/wing/app/Templates/Pulse/default.latte"


def test_wing_has_a_staleness_arm_at_all():
    php = WING.read_text(encoding="utf-8")
    match_block = php[php.find("$r['health'] = match (true)"):]
    match_block = match_block[: match_block.find("};")]
    assert "overdue" in match_block, (
        "Wing's health classifier has no overdue arm again. A job that stops "
        "firing keeps every other field green and falls through to `ok`, which "
        "is the state the page sorts LAST."
    )


def test_overdue_outranks_ok_in_the_sort():
    """Rendering the state is not enough if it prints below everything calm."""
    php = WING.read_text(encoding="utf-8")
    rank_line = next(l for l in php.splitlines() if "$rank = [" in l)
    ranks = dict(re.findall(r"'(\w+)'\s*=>\s*(\d+)", rank_line))
    assert "overdue" in ranks, "overdue is missing from the sort order"
    assert int(ranks["overdue"]) < int(ranks["ok"]), (
        f"overdue sorts at {ranks['overdue']} and ok at {ranks['ok']} — a "
        f"stopped job would print below every healthy one"
    )
    assert int(ranks["overdue"]) < int(ranks["paused"]), (
        "overdue must outrank paused: a deliberate pause is calmer news than a "
        "job nobody paused that stopped anyway"
    )


def _grace_terms(text: str) -> tuple[int, int]:
    """(floor_seconds, jitter_multiplier) from a grace expression.

    Both sides spell it as max(15 * 60, jitter * 60 * 2); this reads the two
    numbers that matter rather than the punctuation, so PHP and TypeScript can
    be compared without either being rewritten to look like the other.
    """
    m = re.search(r"max\(\s*15\s*\*\s*60\s*,(.*?)\*\s*60\s*\*\s*(\d+)\s*\)", text, re.I | re.S)
    assert m, f"no recognisable grace formula found in:\n{text[:400]}"
    # The middle is deliberately unconstrained: PHP spells the jitter lookup
    # `((int) ($job['jitter_min'] ?? 0))` and TypeScript spells it `jitterMin`.
    # An earlier draft of this gate excluded parentheses and commas and so could
    # not read its own PHP side — comparing punctuation instead of the numbers
    # that decide when a job is late.
    assert "jitter" in m.group(1).lower(), (
        f"the grace window no longer derives from jitter: {m.group(1).strip()!r}"
    )
    return 15 * 60, int(m.group(2))


def test_the_grace_window_is_the_same_formula_on_both_sides():
    php = WING.read_text(encoding="utf-8")
    ts = FACE.read_text(encoding="utf-8")

    php_grace = php[php.find("$grace"):]
    php_grace = php_grace[: php_grace.find(";") + 1]
    ts_grace = ts[ts.find("export function graceSeconds"):]
    ts_grace = ts_grace[: ts_grace.find("}") + 1]

    assert _grace_terms(php_grace) == _grace_terms(ts_grace), (
        f"the two surfaces disagree about when a job is late.\n"
        f"  wing: {php_grace.strip()}\n  face: {ts_grace.strip()}\n"
        f"One database, two answers — which is how the face flagged a job the "
        f"backend called healthy for two days."
    )


def test_paused_suppresses_overdue_on_both_sides():
    """A paused job has nothing scheduling it, so "late" is a statement about a
    clock nobody is running. Getting this wrong turns every deliberate pause
    into a permanent alarm, and the operator has nine of them."""
    php = WING.read_text(encoding="utf-8")
    fn = php[php.find("private static function overdueBySeconds"):]
    fn = fn[: fn.find("\n\t}")]
    assert "paused" in fn and "return null" in fn, (
        "Wing's overdue helper does not exempt paused jobs — nine deliberately "
        "paused jobs would report overdue forever"
    )

    ts = FACE.read_text(encoding="utf-8")
    assert re.search(r"paused", ts[ts.find("let overdueBy"): ts.find("let state")], re.I), (
        "the face stopped exempting paused jobs from overdue"
    )


def test_neither_side_calls_an_unscheduled_job_late():
    """A NULL next_fire_at means never scheduled, which `never` already says.
    Reporting it as overdue too would double-count the same job in two states."""
    php = WING.read_text(encoding="utf-8")
    fn = php[php.find("private static function overdueBySeconds"):]
    fn = fn[: fn.find("\n\t}")]
    assert "next_fire_at" in fn and "null" in fn, (
        "the overdue helper no longer guards a missing next_fire_at"
    )


def test_the_operator_page_explains_the_new_state():
    """A badge nobody can decode trains people to ignore badges."""
    latte = TEMPLATE.read_text(encoding="utf-8")
    assert "overdue" in latte, "the Pulse page never mentions overdue"
    assert "$counts['overdue']" in latte, (
        "the header tally omits overdue, so a stopped job adds nothing to the "
        "one line an operator reads first"
    )
