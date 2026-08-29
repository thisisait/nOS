"""Anatomy gate — the harness-enhancement toggle ships OFF and undelegable.

Q6/Q7 (operator, 2026-08-28). Harness enhancement — the loop proposing changes
to the apparatus it is judged BY rather than the estate it is judged ON —
becomes an operator toggle, default OFF, surfaced in a loop editor where the
harnesses are visible before the switch is thrown. Q7 adds the half that is
easy to leave as prose: the toggle itself is on the denylist floor
(docs/idea/11-agentic-loop-contract.md §5.2), because a
permission a system can grant itself is not a permission.

WHAT THIS READS. The ARTIFACTS, not the paragraph above:

  * `state/fixtures/loop-config.seed.yml`     — parsed; the shipped value
  * `state/keap-tables/loop-config.table.yml` — parsed; the column it lands in
  * `budget.ALWAYS_FORBIDDEN` + `budget.check_paths` — the module is IMPORTED
    and the forbidden edit is ATTEMPTED, so the rule has to actually refuse it

The last one is the point. A gate asserting "the string appears in the deny
list" passes against a rule that matches nothing; this one hands `check_paths`
a proposal that edits the fixture and requires a Violation back — the shape
`test_loop_budget_forbids_its_own_gates.py` already uses for the engine's own
source.
"""

from __future__ import annotations

import pathlib
import sys

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
BONE = REPO / "files" / "anatomy" / "bone"
if str(BONE) not in sys.path:
    sys.path.insert(0, str(BONE))

import budget  # noqa: E402 — the enforcement site
import ledger  # noqa: E402 — the enum that names the disabled intent

TABLE_DEF = REPO / "state" / "keap-tables" / "loop-config.table.yml"
FIXTURE = REPO / "state" / "fixtures" / "loop-config.seed.yml"
CONTRACT = REPO / "docs" / "idea" / "11-agentic-loop-contract.md"
PRESENTER = REPO / "files/anatomy/wing/app/Presenters/LoopEditorPresenter.php"

TABLE_SLUG = "loop-config"
ROW_SLUG = "harness_proposals_enabled"

# The gate set is irrelevant to the always-forbidden floor
# (docs/idea/11-agentic-loop-contract.md §5.2) — it applies to every set —
# but check_paths needs one. `repo` is the everyday set.
GATE_SET = "repo"


def _row() -> dict:
    doc = yaml.safe_load(FIXTURE.read_text(encoding="utf-8")) or {}
    rows = doc.get(TABLE_SLUG) or []
    matches = [r for r in rows if isinstance(r, dict) and r.get("slug") == ROW_SLUG]
    assert len(matches) == 1, (
        f"{FIXTURE.relative_to(REPO)} must hold exactly one `{ROW_SLUG}` row "
        f"under `{TABLE_SLUG}:` — found {len(matches)}. Two rows means two "
        f"answers to one question, and the reader takes whichever it meets first."
    )
    return matches[0]


# ── 1. the value that ships ──────────────────────────────────────────────


def test_the_fixture_default_is_off():
    """OFF, and OFF as a boolean.

    `enabled: "false"` is a truthy string in PHP and in Python, and that is not
    a hypothetical: the toggle's whole safety argument is "with it off nothing
    changes behaviour", which a string spelling silently reverses.
    """
    row = _row()
    assert "enabled" in row, f"{ROW_SLUG} declares no `enabled` value at all"
    assert row["enabled"] is False, (
        f"{ROW_SLUG} ships `enabled: {row['enabled']!r}`. It must be the YAML "
        f"boolean false. Shipping it on hands the loop the ability to propose "
        f"changes to its own gates before an operator has consented to any."
    )


def test_the_table_declares_the_column_the_fixture_fills():
    """A fixture whose column the definition does not declare lands nowhere."""
    definition = yaml.safe_load(TABLE_DEF.read_text(encoding="utf-8")) or {}
    columns = {c["key"]: c for c in (definition.get("schema") or {}).get("columns") or []}
    assert columns, f"{TABLE_DEF.relative_to(REPO)} declares no columns"
    undeclared = sorted(set(_row()) - set(columns))
    assert not undeclared, (
        f"{FIXTURE.relative_to(REPO)} sets keys the table does not declare: "
        f"{undeclared}"
    )
    assert columns["enabled"]["kind"] == "boolean", (
        "the `enabled` column must be kind: boolean — a select with three "
        "spellings of off is a switch nothing can gate on"
    )


# ── 2. the denylist, exercised rather than grepped ───────────────────────


@pytest.mark.parametrize("path", [
    str(TABLE_DEF.relative_to(REPO)),
    str(FIXTURE.relative_to(REPO)),
])
def test_the_budget_refuses_a_proposal_that_edits_the_toggle(path):
    """Attempt the forbidden edit. A rule that matches nothing passes a grep."""
    violations = budget.check_paths([path], intent_class="config-fix", gate_set=GATE_SET)
    assert violations, (
        f"budget.check_paths accepted a proposal editing {path}. The loop may "
        f"not propose enabling its own harness editing — Q7 addendum. Add a "
        f"Rule to budget.ALWAYS_FORBIDDEN; being outside ALLOWED_ROOTS is not "
        f"enough, because the deny must survive a root being widened."
    )


def test_the_denylist_names_the_toggle_explicitly():
    """Named, with a reason of its own.

    Not redundant with the test above: `state/**` is outside ALLOWED_ROOTS, so
    the refusal would happen anyway — for the wrong reason, and it would
    evaporate the day someone adds `state/` as an allowed root for a roadmap
    row. An explicit Rule makes that a deliberate act.
    """
    patterns = {r.pattern: r for r in budget.ALWAYS_FORBIDDEN}
    for path in (TABLE_DEF, FIXTURE):
        rel = str(path.relative_to(REPO))
        assert rel in patterns, (
            f"budget.ALWAYS_FORBIDDEN does not name {rel}. Deny-by-default is "
            f"not the same as a stated rule: only the rule tells the proposer "
            f"WHY, and only the rule survives a widened allowed root."
        )
        assert patterns[rel].reason == "operator-consent", (
            f"{rel} is denied for reason {patterns[rel].reason!r} — it is denied "
            f"because the operator's consent is the whole mechanism, and the "
            f"409 should say so."
        )


def test_the_contract_records_the_addendum():
    """The doctrine list and the enforcer must not disagree about the floor."""
    text = CONTRACT.read_text(encoding="utf-8")
    for path in (TABLE_DEF, FIXTURE):
        rel = str(path.relative_to(REPO))
        assert rel in text, (
            f"docs/idea/11-agentic-loop-contract.md §5.2 does not list {rel}. "
            f"The Q7 answer was 'written rather than assumed'."
        )


# ── 3. the seam the editor renders ───────────────────────────────────────


def test_the_disabled_intent_is_still_disabled():
    """The toggle governs `harness`, and `harness` is refused today.

    If this ever goes red because DISABLED_INTENTS emptied, the toggle stopped
    being the thing that decides — and this whole file is measuring a switch
    wired to nothing.
    """
    assert "harness" in ledger.INTENT_CLASSES, (
        "`harness` left the intent enum — the loop editor's seam (3) now lists "
        "an intent class that does not exist"
    )
    assert "harness" in ledger.DISABLED_INTENTS, (
        "`harness` is no longer refused while the toggle it is governed by "
        "still ships OFF. Either the ledger reads the toggle now (then this "
        "gate must read it too) or a refusal was deleted."
    )


def test_the_editor_reads_the_artifacts_it_shows():
    """The surface must render the committed value, not a hardcoded 'OFF'.

    A page that prints OFF regardless is the success-marker defect in reverse:
    it would keep reading OFF the day the fixture says otherwise.
    """
    src = PRESENTER.read_text(encoding="utf-8")
    assert str(FIXTURE.relative_to(REPO)) in src, (
        "LoopEditorPresenter does not read the committed fixture — the state it "
        "shows comes from somewhere else, or from nowhere"
    )
    assert "files/anatomy/bone/ledger.py" in src, (
        "LoopEditorPresenter does not read ledger.py — the intent-class list "
        "on the page is a second copy of a closed enum, and it will drift"
    )
    assert ROW_SLUG in src, "LoopEditorPresenter does not name the toggle row"
