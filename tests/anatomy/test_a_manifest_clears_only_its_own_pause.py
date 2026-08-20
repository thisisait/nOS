"""A declaration that can pause and can never unpause is a one-way door.

THE MEASUREMENT (2026-08-20). `loop:propose` shipped `paused: true` with a
reason naming the bar it was waiting on — §10 step 6, attended cycles before a
cadence. The bar was met. There was then no way to clear it:

  * `PulseRepository` upsert: "Manifest paused=false at update time → no-op."
  * Wing has no per-job resume — no presenter action, no API route.
  * `/admin/resume` deliberately preserves manual pauses; it clears only
    emergency halts.

So the manifest could declare a pause and could never withdraw one, and the only
remaining routes were a hand-written UPDATE against the operator's live wing.db
or building a surface. A state the playbook can enter and cannot leave is drift
by construction, and this estate's whole claim is that the playbook is the
source of truth.

THE RULE THAT WAS ALREADY RIGHT, AND STAYS. A9.3 refuses to silently un-pause a
job THE OPERATOR paused, and that is correct — a converge must not undo a
deliberate halt. What it conflated is two different pauses. `paused_reason`
tells them apart: a manifest declares a specific string, an operator's pause
carries its own or none. So a manifest may now clear a pause ONLY when the
stored reason is byte-identical to the one it declares. Anything else — a
different reason, an empty reason, an emergency halt — is left exactly alone.

WHAT THIS FILE PINS. The three branches, by name, because the middle one is new
and the third is the safety property the middle one must not cost:

  paused=1 declared           → pause, and record the reason
  paused=0, reason MATCHES    → clear (this manifest withdrawing its own)
  paused=0, reason DIFFERS    → leave it; that pause belongs to somebody else

CI-safe: source reading. The behaviour itself was verified live on 2026-08-20 —
`loop:propose` went paused=1 → paused=0 with a null reason across one converge,
while nothing else moved.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
REPOSITORY = REPO / "files/anatomy/wing/app/Model/PulseRepository.php"
MANIFEST = REPO / "files/anatomy/plugins/loop-base/plugin.yml"


def _upsert_update_branch() -> str:
    """The UPDATE arm of the upsert — where an existing row is reconciled."""
    src = REPOSITORY.read_text(encoding="utf-8")
    start = src.index("A9.3")
    end = src.index("First-insert", start)
    return src[start:end]


def test_the_sources_are_readable():
    """Positive control: every assertion below reads one of these."""
    assert REPOSITORY.is_file() and MANIFEST.is_file()
    assert "paused" in _upsert_update_branch()


def test_a_manifest_can_still_declare_a_pause():
    branch = _upsert_update_branch()
    assert re.search(r"\(int\)\s*\$payload\['paused'\]\s*===\s*1", branch), (
        "the manifest can no longer PAUSE a job; that is the original purpose "
        "and the remediator precedent depends on it"
    )


def test_a_manifest_can_withdraw_the_pause_it_declared():
    branch = _upsert_update_branch()
    assert re.search(r"\(int\)\s*\$payload\['paused'\]\s*===\s*0", branch), (
        "there is no branch for a manifest declaring paused=false, so a "
        "declared pause is once again a one-way door — the state `loop:propose` "
        "was stuck in on 2026-08-20"
    )
    assert "$update['paused'] = 0;" in branch, "the clearing branch sets nothing"


def test_it_clears_only_when_the_STORED_reason_matches_the_declared_one():
    """The safety property. Without the comparison this becomes A9.3's defect."""
    branch = _upsert_update_branch()
    assert "paused_reason" in branch and "$existing->paused_reason" in branch, (
        "the clearing branch does not read the STORED reason, so it cannot "
        "tell its own pause from an operator's"
    )
    assert re.search(r"\$declared\s*===\s*\$stored", branch), (
        "the clearing branch does not COMPARE the declared reason with the "
        "stored one — it would then un-pause a job the operator halted, which "
        "is exactly what A9.3 exists to prevent"
    )
    assert re.search(r"\$declared\s*!==\s*''", branch), (
        "an EMPTY declared reason must not match an empty stored one and clear "
        "a pause nobody declared"
    )


def test_the_loop_propose_manifest_keeps_the_reason_it_is_withdrawing():
    """The mechanism only works while the two strings stay byte-identical."""
    # PARSED, not sliced. The first draft took 1800 characters from the job's
    # name and broke the moment a comment grew above `paused_reason` — a gate
    # that fails on formatting teaches its reader to distrust it.
    import yaml  # noqa: PLC0415

    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    jobs = {j.get("name"): j for j in (manifest.get("pulse") or {}).get("jobs", [])}
    assert "propose" in jobs, f"no `propose` job in the manifest; found {list(jobs)}"
    job = jobs["propose"]
    assert job.get("paused") is False, "loop:propose is paused again — deliberately?"
    assert job.get("paused_reason"), (
        "the reason was removed while paused: false is still declared. The "
        "upsert matches on that string; without it the clear silently stops "
        "happening and nobody learns until the job does not fire."
    )
