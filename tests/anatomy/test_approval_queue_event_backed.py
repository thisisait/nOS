"""Anatomy CI gate: approval queue is event-backed by design (DEFERRED table).

Finding ``approval-queue-persistence`` (low / tech-debt, confirmed): the
agent-action approval queue stores requests + decisions as ``events`` rows
(``agent_approval_request`` / ``agent_approval_decision``, paired on
``actor_action_id``) rather than in a dedicated ``approval_requests`` table.

Verdict (both reviewers): the event-based model is **architecturally
correct** — events are the single source of truth for audit, so a side
table would duplicate that lineage and risk drift. The proposed fix is a
**deferral**: revisit (dedicated table OR a read-only ``/api/v1/approvals``
endpoint) only when a SECOND agent ships that programmatically gates on
approvals — conductor (the sole live agent) does not.

This gate pins that decision so it can't drift silently:

  1. NO ``approval_requests`` (or ``approval_decisions``) table is ever
     declared in the Wing schema — if one appears, the deferral has been
     un-deferred and this contract + the presenter docblock must be
     re-reviewed together.
  2. The ``/approvals`` read path goes through ``EventRepository``
     (``listPendingApprovals`` / ``listRecentDecisions``) — never raw SQL
     in the presenter.
  3. The presenter docblock carries the explicit DEFERRED marker + the
     trigger condition, so a future maintainer reads the rationale before
     adding a side table.

Like the sibling A13.7 gates, this test parses source files with regex
(no PHP execution) so the CI runner stays on the pytest + pyyaml stack.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WING = REPO_ROOT / "files" / "anatomy" / "wing"
PRESENTER = WING / "app" / "Presenters" / "ApprovalsPresenter.php"
EVENT_REPO = WING / "app" / "Model" / "EventRepository.php"
DB_DIR = WING / "db"


def _schema_sql() -> str:
    """Concatenate every .sql file under the Wing db/ tree."""
    return "\n".join(p.read_text() for p in sorted(DB_DIR.glob("*.sql")))


def test_no_dedicated_approval_table_in_schema():
    """The deferral holds only while there is NO dedicated approval table.
    A ``CREATE TABLE approval_requests`` (or ``approval_decisions``) means
    the event-source model was abandoned — fail loudly so the docblock +
    this contract get re-reviewed in lock-step (not silently superseded).
    """
    sql = _schema_sql()
    for table in ("approval_requests", "approval_decisions", "agent_approvals"):
        assert not re.search(
            rf"create\s+table\s+(if\s+not\s+exists\s+)?[\"`']?{table}\b",
            sql, re.IGNORECASE,
        ), (
            f"A dedicated `{table}` table appeared in the Wing schema. The "
            f"approval queue was DEFERRED to the event-backed model on purpose "
            f"(events = single source of truth for audit). Un-deferring it "
            f"requires re-reviewing ApprovalsPresenter's docblock + this gate "
            f"together — update both, then adjust this assertion."
        )


def test_read_path_uses_event_repository_not_raw_sql():
    """The presenter must query the approval queue via EventRepository, not
    by reaching into the DB with raw SQL. This is what makes the event store
    the single canonical read surface (and keeps audit semantics uniform)."""
    src = PRESENTER.read_text()
    assert "listPendingApprovals" in src and "listRecentDecisions" in src, (
        "ApprovalsPresenter no longer reads through "
        "EventRepository::listPendingApprovals / listRecentDecisions — the "
        "event-backed read contract has drifted."
    )
    # No raw query against an approval-specific table from inside the presenter.
    assert not re.search(
        r"->query\(|->table\(\s*['\"]approval", src, re.IGNORECASE
    ), (
        "ApprovalsPresenter reaches the DB with raw SQL / an approval table — "
        "the read path must go through EventRepository (events source-of-truth)."
    )


def test_event_repository_pairs_request_with_decision_on_actor_action_id():
    """The event-source model relies on request/decision rows being paired by
    actor_action_id (a pending request = a request event with no matching
    decision event). Pin both event types + the pairing column so a refactor
    can't quietly break the 'pending = undecided' definition."""
    src = EVENT_REPO.read_text()
    assert "agent_approval_request" in src and "agent_approval_decision" in src, (
        "EventRepository no longer references both approval event types — "
        "the event-backed pairing model is gone."
    )
    m = re.search(
        r"public function listPendingApprovals\([^)]*\)\s*:\s*array\s*\{(.+?)\n\t\}",
        src, re.DOTALL,
    )
    assert m, "listPendingApprovals body not parseable"
    body = m.group(1)
    assert "actor_action_id" in body, (
        "listPendingApprovals no longer pairs request/decision on "
        "actor_action_id — pending-detection is broken."
    )


def test_presenter_documents_the_deferral_and_trigger():
    """The deferral decision (no dedicated table) + its revisit trigger must
    live in the presenter docblock, so a future maintainer reads WHY before
    adding a side table. This is the human-facing half of the contract that
    this gate enforces structurally."""
    src = PRESENTER.read_text()
    # Collapse the comment-prefix line wrapping (" * ") + whitespace so a
    # phrase that the formatter split across lines still matches as prose.
    prose = re.sub(r"\s*\*\s*", " ", src)
    prose = re.sub(r"\s+", " ", prose)
    assert "DEFERRED" in src and "approval_requests" in src, (
        "ApprovalsPresenter docblock no longer records the DEFERRED "
        "no-dedicated-table decision — restore the rationale + trigger."
    )
    assert "single source of truth" in prose, (
        "ApprovalsPresenter docblock dropped the 'events = single source of "
        "truth' rationale for the deferral."
    )
    assert "second agent" in prose.lower(), (
        "ApprovalsPresenter docblock dropped the revisit trigger (a SECOND "
        "agent that programmatically gates on approvals)."
    )
