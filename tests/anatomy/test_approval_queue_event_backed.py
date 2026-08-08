"""Anatomy CI gate: ONE approval surface, split lineage/resolution by design.

HISTORY, because this file's three previous assertions encoded a real decision
and a deleted gate reads as a lifted constraint.

A11 (2026-05-07) stored approvals as paired ``events`` rows
(``agent_approval_request`` / ``agent_approval_decision`` on
``actor_action_id``) and THIS gate forbade a dedicated table, on the correct
ground that events are the single source of truth for audit. It also named its
own revisit trigger: *"a SECOND surface that programmatically gates on
approvals"*. ``agents-inbox`` (2026-08-08) is that surface, so the deferral
came due — and retired A11 rather than duplicating it, because the estate had
measured what the append-only model cannot do: two operators clicking Approve
in the same instant both append a decision, the reader filtered on merely
HAVING one, and approve + reject read as "decided" with the winner being
whichever row a reader met first. Nothing detected it. A11's write path also
carried two silent failures (return-on-empty-HMAC-secret, discarded
``curl_exec`` result). Measured on the live estate before retirement: ZERO
``agent_approval_*`` events — nothing to migrate.

THE SUCCESSOR CONTRACT this file now pins:

  events           the LINEAGE — append-only; ``agent_approval_request`` /
                   ``agent_approval_decision`` are STILL the event types an
                   approval emits, so every audit query keyed on them survives.
  agent_questions  the RESOLUTION — exactly one row, closed by a conditional
                   UPDATE (``kind='approval'``); the decision event is emitted
                   only on the winning write, in-process.

Every assertion reads code (comments stripped, scoped to the smallest
syntactic unit), never prose.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WING = REPO_ROOT / "files" / "anatomy" / "wing"
APP = WING / "app"
RETIRED_PRESENTER = APP / "Presenters" / "ApprovalsPresenter.php"
RETIRED_TEMPLATE_DIR = APP / "Templates" / "Approvals"
ROUTER = APP / "Core" / "RouterFactory.php"
REPOSITORY = APP / "Model" / "AgentQuestionRepository.php"
EVENT_REPO = APP / "Model" / "EventRepository.php"
DB_DIR = WING / "db"


def _code_only_php(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"^\s*//.*$", "", src, flags=re.M)


def _schema_sql() -> str:
    return "\n".join(p.read_text() for p in sorted(DB_DIR.glob("*.sql")))


def test_the_a11_surface_is_gone():
    """Presenter, template and verb routes are retired — not half-retired.

    A dead nav entry or a routed-but-presenterless verb is worse than either
    state alone: the operator meets a control that 500s or silently no-ops.
    """
    assert not RETIRED_PRESENTER.exists(), (
        "ApprovalsPresenter.php is back. Approvals are kind='approval' "
        "questions answered on /inbox; a second decision surface reintroduces "
        "the append-only race this file's docblock records."
    )
    assert not RETIRED_TEMPLATE_DIR.exists(), (
        "Templates/Approvals/ is back without its presenter — a template "
        "nothing renders, or a resurrected surface. Neither is intended."
    )
    router_code = _code_only_php(ROUTER.read_text())
    verb_routes = re.findall(r"addRoute\('approvals/[^']*'", router_code)
    assert not verb_routes, (
        f"RouterFactory still routes A11 verb forms: {verb_routes} — these "
        "targeted ApprovalsPresenter::actionApprove/actionReject, which no "
        "longer exist."
    )


def test_the_legacy_url_lands_on_the_successor():
    """/approvals redirects to /inbox rather than 404ing. Bookmarks and
    muscle memory learn the successor; a 404 teaches nothing."""
    router_code = _code_only_php(ROUTER.read_text())
    assert re.search(r"addRoute\('approvals',\s*'Inbox:approvals'\)", router_code), (
        "the bare 'approvals' route no longer lands on Inbox:approvals — "
        "either restore the redirect route or update this gate alongside a "
        "deliberate decision to 404."
    )
    inbox = _code_only_php((APP / "Presenters" / "InboxPresenter.php").read_text())
    m = re.search(
        r"public function actionApprovals\(\)\s*:\s*void\s*\{(.*?)\n\t\}",
        inbox, re.DOTALL,
    )
    assert m and "redirectPermanent" in m.group(1), (
        "InboxPresenter::actionApprovals() does not permanently redirect to "
        "the inbox — the legacy URL must answer with the successor, not 404."
    )


def test_still_no_second_approval_store_in_schema():
    """Carried forward from the original gate, strengthened: the RESOLUTION
    lives in agent_questions and nowhere else. A second store means two
    places can disagree about whether something is decided."""
    sql = _schema_sql()
    for table in ("approval_requests", "approval_decisions", "agent_approvals"):
        assert not re.search(
            rf"create\s+table\s+(if\s+not\s+exists\s+)?[\"`']?{table}\b",
            sql, re.IGNORECASE,
        ), (
            f"A dedicated `{table}` table appeared in the Wing schema. The "
            f"resolution store is agent_questions (kind='approval'); a second "
            f"store reintroduces the drift the A11 gate was protecting against."
        )
    assert re.search(
        r"create\s+table\s+(if\s+not\s+exists\s+)?[\"`']?agent_questions\b",
        sql, re.IGNORECASE,
    ), (
        "agent_questions vanished from the schema — the resolution store is "
        "gone while this gate still certifies it."
    )


def test_the_approval_event_types_survive_and_have_one_writer():
    """The lineage keeps A11's vocabulary — and exactly one code path writes
    the decision event: AgentQuestionRepository, on the winning UPDATE.

    Comment-stripped, so a docblock recalling A11 cannot satisfy (or trip)
    this. EventRepository may carry the literals only in its VALID_TYPES
    registry; no presenter may emit a decision on its own.
    """
    repo_code = _code_only_php(REPOSITORY.read_text())
    assert "'agent_approval_request'" in repo_code, (
        "AgentQuestionRepository no longer emits agent_approval_request for "
        "kind='approval' asks — audit queries keyed on A11's types break."
    )
    assert "'agent_approval_decision'" in repo_code, (
        "AgentQuestionRepository no longer emits agent_approval_decision on "
        "the winning answer — the lineage loses the decision."
    )

    writers = []
    for php in APP.rglob("*.php"):
        if php == REPOSITORY or php == EVENT_REPO:
            continue
        code = _code_only_php(php.read_text(encoding="utf-8"))
        if "agent_approval_decision" in code:
            writers.append(str(php.relative_to(REPO_ROOT)))
    assert not writers, (
        f"agent_approval_decision appears in code outside AgentQuestionRepository "
        f"/ EventRepository's registry: {writers}. The decision event must be "
        f"emitted ONLY on the winning conditional UPDATE — a second writer is "
        f"how approve+reject both got recorded under A11."
    )


def test_the_decision_event_rides_the_winning_update():
    """The emit sits inside the `$affected === 1` branch of answer() AND of
    answerAsOperator() — never before the UPDATE, never unconditionally."""
    code = _code_only_php(REPOSITORY.read_text())
    for method in ("public function answer(", "public function answerAsOperator("):
        start = code.find(method)
        assert start != -1, f"{method} not found in AgentQuestionRepository"
        # Body up to the next public method.
        nxt = code.find("public function", start + len(method))
        body = code[start : nxt if nxt != -1 else len(code)]
        cond = body.find("$affected === 1")
        emit = body.find("$this->emit(")
        assert cond != -1 and emit != -1 and emit > cond, (
            f"in {method} the decision emit does not follow the "
            f"affected-row check — a losing (or failed) answer could emit a "
            f"decision event, which is exactly the A11 defect."
        )
