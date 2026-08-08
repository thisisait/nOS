"""Two ways to answer a question, and the authorisation each one skips.

`AgentQuestionRepository` exposes two answer paths:

  answer()            requires the per-question reply token in its WHERE
                      clause. Safe for any caller, because holding the token
                      IS the authorisation.
  answerAsOperator()  takes NO token. It exists because inside Wing the
                      Authentik forward-auth session is the stronger
                      authorisation — it names a person. Which means it skips
                      the only check that stops an arbitrary caller answering,
                      and it is safe ONLY while every call site sits behind an
                      RBAC gate.

This file is the gate the repository's docblock cites. It was cited before it
existed — prose claiming an enforcement nobody had written (found reviewing
the completion plan, 2026-08-08). Now it reads code:

1. Every call site of `answerAsOperator(` outside the repository must be a
   browser presenter declaring `$minAccessTier = 1` (the declarative gate
   BasePresenter::startup() enforces). An API presenter must never call it:
   a bearer token names a service, not a person, and "who approved this"
   must name someone.

2. The token path's HTTP endpoint must refuse an ANONYMOUS identity. A
   channel adapter that cannot map its chat identity to an operator must be
   refused, not recorded as 'unknown' — and the presenter must not quietly
   substitute the bearer token's own name (a service, not a person) for the
   missing operator.

Comments are stripped before matching; assertions scope to the smallest
syntactic unit (a method body, a call's argument list).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
APP = REPO / "files/anatomy/wing/app"
REPOSITORY = APP / "Model/AgentQuestionRepository.php"
API_PRESENTER = APP / "Presenters/Api/InboxPresenter.php"


def code_only(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"^\s*//.*$", "", src, flags=re.M)


def call_sites() -> dict[Path, str]:
    """path -> comment-stripped source, for every file that CALLS
    answerAsOperator (declaration site excluded)."""
    out: dict[Path, str] = {}
    for php in APP.rglob("*.php"):
        if php == REPOSITORY:
            continue
        code = code_only(php.read_text(encoding="utf-8"))
        if re.search(r"->answerAsOperator\s*\(", code):
            out[php] = code
    return out


def test_every_token_less_answer_sits_behind_a_tier_gate():
    sites = call_sites()
    assert sites, (
        "nothing calls answerAsOperator() any more — either the browser "
        "answer path is gone (a regression: /inbox can no longer decide) or "
        "the method was renamed; re-point this gate rather than letting it "
        "pass vacuously."
    )
    offenders = []
    for path, code in sites.items():
        rel = str(path.relative_to(REPO))
        if "/Presenters/Api/" in rel.replace("\\", "/"):
            offenders.append(f"{rel}: API presenters authenticate services, not people")
            continue
        if not re.search(r"\$minAccessTier\s*=\s*1\s*;", code):
            offenders.append(f"{rel}: no `$minAccessTier = 1` declaration")
    assert not offenders, (
        "answerAsOperator() — the path that skips the reply-token check — is "
        "called from an ungated place:\n  " + "\n  ".join(offenders)
        + "\n\nIt is safe ONLY behind an RBAC gate that names a person. "
        "Gate the caller or make it present the token."
    )


def _action_answer_body() -> str:
    code = code_only(API_PRESENTER.read_text(encoding="utf-8"))
    m = re.search(
        r"public function actionAnswer\([^)]*\)\s*:\s*void\s*\{(.*?)\n\t\}",
        code, re.DOTALL,
    )
    assert m, "Api\\InboxPresenter::actionAnswer body not parseable"
    return m.group(1)


def test_the_token_path_refuses_an_anonymous_identity():
    body = _action_answer_body()
    # The refusal must exist: an empty answered_by is an error, before the
    # repository is reached.
    assert re.search(r"\$answeredBy\s*===\s*''", body), (
        "actionAnswer no longer refuses an empty answered_by — an anonymous "
        "approval is an audit dead end; a channel that cannot name the "
        "operator must be refused, not recorded."
    )
    # And there must be no silent substitution of a service identity for the
    # missing person: the old fallback chain was
    # `$b['answered_by'] ?? $this->getActorId() ?? 'unknown'`. (Refusing a
    # LITERAL 'unknown' input is fine and expected; defaulting to one is not
    # — hence the `??` shape, not the bare string, is what is forbidden.)
    assert "getActorId" not in body and "?? 'unknown'" not in body, (
        "actionAnswer falls back to the bearer token's name (or 'unknown') "
        "when answered_by is missing. A service token is not a person; "
        "\"who approved this\" must name someone or the call must fail."
    )


def test_a_non_person_identity_is_refused_by_shape():
    """`agent:*` and `channel:*` are the two non-person spellings the estate
    already uses for actor_id — an adapter passing its OWN identity as the
    answerer must be caught even when it is not empty."""
    body = _action_answer_body()
    for prefix in ("agent:", "channel:"):
        assert f"'{prefix}'" in body, (
            f"actionAnswer no longer refuses answered_by values shaped "
            f"`{prefix}*`. That spelling names an actor that is not a person "
            f"— recording it as the decider is the audit dead end the plan's "
            f"own trap list named."
        )
