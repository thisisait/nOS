"""Every ask and every answer leaves exactly one event, and the answer leaves one.

WHY THIS FILE IS SHAPED FOR READERS, NOT FOR A GREEN TICK. The operator asked
for tests the judges and SERE can benefit from. A gate that only says PASS gives
a downstream reader nothing: the loop cannot learn from a tick. So this file
asserts the LINEAGE CONTRACT — the facts a reader will later query — and names
each one in terms of the question it answers:

    was it asked?          exactly one `*_asked` / `agent_approval_request`
    was it answered?       at most one decision, ever, per question uuid
    who answered, how?     actor_id + result.via
    how long did it hang?  result.waited_seconds
    is it still open?      the table, not the log

THE DESIGN IT PINS (decided 2026-08-08, merging A11 `/approvals` in):

    events           the LINEAGE — append-only, read by audit/judges/SERE
    agent_questions  the RESOLUTION — one row, holds "is this still open"

An append-only log cannot enforce resolve-once. A11 demonstrates the cost: two
operators clicking Approve at the same instant both append a decision, and
`listPendingApprovals` filters on the mere existence of one — so if one approved
and one rejected, the queue reads "decided" and the winner is whoever the reader
sees first. Nothing detects it. Here the event is emitted only on the winning
conditional UPDATE, so one question yields at most one decision by construction.

Measured before merging: the live estate holds ZERO `agent_approval_*` events.
A11's surface has never been used, so there is nothing to migrate — which is why
this could be done now rather than negotiated.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WING = REPO / "files/anatomy/wing"
QUESTIONS = WING / "app/Model/AgentQuestionRepository.php"
EVENTS_PHP = WING / "app/Model/EventRepository.php"
EVENTS_PY = REPO / "files/anatomy/bone/events.py"
APPROVALS = WING / "app/Presenters/ApprovalsPresenter.php"

ASK_TYPES = ("agent_question_asked", "agent_approval_request")
ANSWER_TYPES = ("agent_question_answered", "agent_approval_decision")


def src() -> str:
    return QUESTIONS.read_text(encoding="utf-8")


def method(name: str, until: str) -> str:
    s = src()
    a, b = s.find(f"public function {name}"), s.find(f"public function {until}")
    assert a != -1 and b > a, f"cannot slice {name}() — the class shape changed"
    return s[a:b]


def test_asking_emits_exactly_one_lineage_event():
    body = method("ask", "answer")
    assert body.count("$this->emit(") == 1, (
        "ask() emits other than exactly one event. Two would double-count a "
        "question in every audit query; zero would make it invisible to the "
        "judges and to SERE."
    )
    for t in ASK_TYPES:
        assert t in body, f"ask() no longer emits {t}"


def answer_paths() -> dict[str, str]:
    """Every method that can resolve a question, by name.

    There are two by design — one authorised by a reply token (no session, the
    operator in Telegram), one by an Authentik forward-auth identity (Wing). The
    invariant below must hold for BOTH, so this is discovered rather than
    listed: a third answer path added later is covered automatically instead of
    slipping past a hard-coded pair.

    Discovered the hard way: this test originally sliced `answer` -> `poll` and
    went red the moment `answerAsOperator` was inserted between them. The gate
    was right that something changed; the fix was to widen the invariant, not to
    re-slice around the new method.
    """
    s = src()
    names = re.findall(r"public function (answer\w*)\(", s)
    assert names, "no answer path found — the class shape changed"
    bounds = sorted(
        (s.find(f"public function {n}("), n)
        for n in set(re.findall(r"public function (\w+)\(", s))
    )
    out = {}
    for i, (pos, name) in enumerate(bounds):
        if name not in names:
            continue
        end = bounds[i + 1][0] if i + 1 < len(bounds) else len(s)
        out[name] = s[pos:end]
    return out


def test_only_the_winning_answer_emits_a_decision():
    """The property A11's append-only path structurally cannot have."""
    paths = answer_paths()
    assert len(paths) >= 2, (
        f"expected at least the token path and the session path, found {list(paths)}"
    )
    for name, body in paths.items():
        assert body.count("$this->emit(") == 1, (
            f"{name}() emits other than exactly one event."
        )
        win = body.find("$affected === 1")
        emit = body.find("$this->emit(")
        assert win != -1 and win < emit, (
            f"{name}() emits its decision event OUTSIDE the winning branch. A "
            "loser must not append a decision — that is exactly how A11 ends up "
            "with two verdicts for one request and no way to tell which counted."
        )
        assert "'status', 'open'" in body, (
            f"{name}() no longer carries the open-status precondition in its "
            "UPDATE, so resolve-once does not hold on this path."
        )


def test_the_lineage_carries_what_a_reader_needs():
    """Each of these is a question a judge or SERE will actually ask."""
    body = method("answer", "poll")
    for field, why in [
        ("verdict", "what was decided"),
        ("operator_username", "who decided it"),
        ("via", "which channel it came back through"),
        ("waited_seconds", "how long the run was blocked — the loop's cost signal"),
    ]:
        assert field in body, (
            f"the decision event no longer carries `{field}` ({why}). A reader "
            "cannot derive it later: the row is append-only and the moment has "
            "passed."
        )


def test_the_lineage_key_is_the_question_uuid():
    """One SELECT must reconstruct ask -> answer (the A10 contract)."""
    body = src()[src().find("private function emit") :][:900]
    assert "'actor_action_id' => $uuid" in body, (
        "the emitted event no longer keys actor_action_id to the question uuid, "
        "so ask and answer cannot be joined and the lineage is two unrelated "
        "rows."
    )


def emit_arguments(body: str) -> str:
    """Just what is passed to `$this->emit(...)`, balanced-paren scanned.

    Scoped deliberately. Slicing from the call to the end of the method was
    tried and failed on ask()'s own `return ['uuid' => …, 'reply_token' => …]`
    — the ONE legitimate place the token appears, handed back to the caller that
    filed the question. A gate that reads past its subject punishes correct code;
    that mistake was made four times in one day on this feature and each time it
    was the gate, never the implementation.
    """
    start = body.find("$this->emit(")
    assert start != -1, "no emit() call found"
    i = body.find("(", start)
    depth = 0
    while i < len(body):
        if body[i] == "(":
            depth += 1
        elif body[i] == ")":
            depth -= 1
            if depth == 0:
                return body[start:i]
        i += 1
    raise AssertionError("unbalanced parentheses in the emit() call")


def code_only(php: str) -> str:
    """PHP with comments stripped.

    Needed because the emit block's own comment reads "NO reply_token …" — a
    gate that matched it would fail precisely on the code that documents the
    rule being enforced. Twice today a gate on this feature punished its own
    explanation; both times the fix was to read code, never prose.
    """
    php = re.sub(r"/\*.*?\*/", "", php, flags=re.S)
    return re.sub(r"//.*$", "", php, flags=re.M)


def test_no_credential_enters_the_lineage():
    """Events are read widely — the same rule as notifications."""
    emit_block = code_only(emit_arguments(method("ask", "answer")))
    assert "reply_token" not in emit_block and "$token" not in emit_block, (
        "the ask event carries the reply token. Events are read by /timeline, "
        "by the judges and by SERE; a credential in the lineage is a credential "
        "in every one of those readers."
    )


def test_both_vocabularies_know_the_new_types():
    """Twin rule: a type on one side only makes a proxied replay 400."""
    php = EVENTS_PHP.read_text(encoding="utf-8")
    py = EVENTS_PY.read_text(encoding="utf-8")
    for t in ("agent_question_asked", "agent_question_answered"):
        assert t in php, f"Wing's VALID_TYPES is missing {t}"
        assert t in py, f"Bone's VALID_TYPES is missing {t}"


def test_the_a11_race_is_recorded_where_someone_will_find_it():
    """The defect that motivated the merge must not become folklore.

    A11's decision path is still append-only and its writer still discards the
    HTTP result. Until that presenter is retired or repaired, the reasoning has
    to live somewhere a maintainer will actually meet it.
    """
    assert "resolve-once" in src() or "append-only" in src(), (
        "AgentQuestionRepository no longer explains why a resolution table "
        "exists beside an append-only log. Without it the table looks like the "
        "duplicate the A11 gate forbids."
    )
    approvals = APPROVALS.read_text(encoding="utf-8")
    assert "curl_exec($ch);" in approvals, (
        "ApprovalsPresenter::postDecision changed — if the discarded result was "
        "fixed, say so and delete this assertion; if the presenter was retired, "
        "delete this test. Do not leave it asserting a fault that is gone."
    )
