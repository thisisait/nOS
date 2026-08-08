"""Anatomy CI gates for Wing presenter authorization (A13.7, 2026-05-07).

This file pins the security boundaries surfaced by the A13.7 security review:

  1. Every Wing presenter that performs state mutation (anything in
     ``_PRIVILEGED_PRESENTERS``) MUST override ``startup()`` and call
     ``$this->requireSuperAdmin()`` (or ``requireGroup(...)``) — the gate
     lives in BasePresenter so future presenters get protection by default.
  2. Every state-changing ``actionXxx()`` method on those presenters MUST
     call ``$this->requirePostMethod()`` so a phishing GET (top-level
     navigation, ``<img src>``, ``window.open``) cannot trigger the
     mutation. The corresponding Latte template MUST use a
     ``<form method="post">`` — links via ``<a href>`` are forbidden.
  3. The ``BasePresenter::requireSuperAdmin()`` helper MUST gate on the
     literal ``nos-providers`` group. A rename in default.config.yml has
     to be matched by a code change here — the tier mapping isn't
     allowed to drift silently.

The original A13.7 finding: ``ApprovalsPresenter`` shipped without any
RBAC gate — any authenticated user (incl. tier-4 ``nos-guests``) could
approve agent actions. Root cause: the gate was a private method on
``AdminPresenter``, so adding a sibling presenter required remembering
to copy it. After A13.7 the gate is on ``BasePresenter`` and these tests
make "I forgot" loud.

These tests do NOT execute PHP — they parse source files with regex,
which is enough for the contract assertions and lets the CI runner stay
on the existing pytest+pyyaml stack.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
PRESENTERS = REPO_ROOT / "files" / "anatomy" / "wing" / "app" / "Presenters"
TEMPLATES  = REPO_ROOT / "files" / "anatomy" / "wing" / "app" / "Templates"
BASE_PRESENTER = PRESENTERS / "BasePresenter.php"


# Presenters that must require super-admin on EVERY action (read + write).
# Add new privileged presenters here when they land.
_PRIVILEGED_PRESENTERS: list[tuple[str, Path, list[str]]] = [
    # (presenter_name, source_path, list_of_state_changing_actions)
    (
        "AdminPresenter",
        PRESENTERS / "AdminPresenter.php",
        ["actionHalt", "actionResume"],
    ),
    (
        # InboxPresenter became privileged on 2026-08-08: it used to only SHOW
        # things, it now DECIDES them — actionAnswer can authorise an agent
        # action, which is what A11's ApprovalsPresenter (retired the same
        # day) gated with requireSuperAdmin(). Gate is the declarative
        # `$minAccessTier = 1` enforced by BasePresenter::startup().
        "InboxPresenter",
        PRESENTERS / "InboxPresenter.php",
        ["actionAnswer", "actionMarkRead"],
    ),
    (
        # Browser-side AgentsPresenter (NOT the Api/ one). actionStart proxies
        # POST /api/v1/agents/<name>/sessions with the daemon's WING_API_TOKEN
        # — without the requireSuperAdmin gate, any authenticated wing user
        # gains agent-runner authority under daemon credentials. Added 2026-
        # 05-07 after security-review surfaced the gap (A13.7-class issue).
        "AgentsPresenter",
        PRESENTERS / "AgentsPresenter.php",
        ["actionStart"],
    ),
    (
        # UpgradesPresenter::actionQueueUpgrade (W5-B2) inserts into
        # upgrades_planned, which the engine auto-applies under `--tags
        # upgrade`. Gated Tier-1 via the declarative `$minAccessTier = 1`
        # (enforced by BasePresenter::startup()) rather than a startup()
        # override. Added 2026-05-30 after security-review flagged the missing
        # gate (same A13.7 class as ApprovalsPresenter).
        # actionCancelPlanned (F3, 2026-06-18) flips a queued upgrades_planned
        # row planned → cancelled (the "Unqueue" control, the machinery path to
        # re-test the plan-choice flow). Same Tier-1 + CSRF boundary as
        # actionQueueUpgrade — a GET-based unqueue would be a phishing-link CSRF.
        "UpgradesPresenter",
        PRESENTERS / "UpgradesPresenter.php",
        ["actionQueueUpgrade", "actionCancelPlanned"],
    ),
    (
        # BreachesPresenter (gov P1) — Tier-1 READ-ONLY GDPR breach register +
        # deadline countdowns. No state-changing browser actions (filing runs
        # through bin/breach-file.php), so the mutator list is empty; the gate
        # is the declarative `$minAccessTier = 1` enforced by BasePresenter.
        "BreachesPresenter",
        PRESENTERS / "BreachesPresenter.php",
        [],
    ),
    (
        # GdprPresenter (S4) — the /gdpr browser view lists the Art-30 register,
        # the DSAR log, and the breach register: EVERY data subject's email +
        # request history. Same sensitivity as BreachesPresenter (which gates the
        # same breach data) -> Tier-1 via the declarative `$minAccessTier = 1`.
        # Read-only view (mutations run through bin/record-dsar.php etc.), so the
        # mutator list is empty.
        "GdprPresenter",
        PRESENTERS / "GdprPresenter.php",
        [],
    ),
]


def _startup_body(src: str) -> str | None:
    m = re.search(
        r"public function startup\(\)\s*:\s*void\s*\{(.+?)\n\t\}",
        src, re.DOTALL,
    )
    return m.group(1) if m else None


def _is_tier_gated(src: str) -> bool:
    """A presenter is privilege-gated if EITHER it overrides startup() and
    calls a tier helper there, OR it declares `$minAccessTier = <1..3>`
    (enforced centrally by BasePresenter::startup())."""
    body = _startup_body(src)
    if body is not None and (
        "requireSuperAdmin()" in body
        or "requireGroup(" in body
        or "requireTier(" in body
    ):
        return True
    return bool(re.search(r"\$minAccessTier\s*=\s*[1-4]\s*;", src))


# ── Base-class contract ─────────────────────────────────────────────


def test_base_presenter_exposes_required_helpers():
    """``BasePresenter`` must define the canonical authorization +
    state-mutation helpers — every privileged subclass calls these."""
    src = BASE_PRESENTER.read_text()
    for helper in (
        "protected function requireSuperAdmin",
        "protected function requireGroup",
        "protected function requirePostMethod",
        "protected function callerHasGroup",
        "protected function requireTier",
    ):
        assert helper in src, f"BasePresenter missing helper: {helper}"


def test_min_access_tier_enforced_by_default_in_base_startup():
    """The declarative gate must actually be wired: BasePresenter::startup()
    has to enforce ``$minAccessTier`` via ``requireTier()`` for EVERY presenter,
    and ``requireTier`` must abort with 403. Otherwise a subclass could set the
    property believing it's gated while the action runs wide open."""
    src = BASE_PRESENTER.read_text()
    body = _startup_body(src)
    assert body is not None, "BasePresenter has no startup() body"
    assert "minAccessTier" in body and "requireTier(" in body, (
        "BasePresenter::startup() no longer enforces $minAccessTier via "
        "requireTier — the declarative RBAC gate is dead code"
    )
    m = re.search(
        r"protected function requireTier\([^)]*\)\s*:\s*void\s*\{(.+?)\n\t\}",
        src, re.DOTALL,
    )
    assert m, "requireTier body not parseable"
    assert "403" in m.group(1) and "$this->error" in m.group(1), (
        "requireTier must abort with $this->error(..., 403)"
    )


def test_super_admin_gate_pins_correct_groups():
    """``requireSuperAdmin`` must gate on the **two** Tier-1 group
    literals per CLAUDE.md RBAC table: ``nos-providers`` AND
    ``nos-admins``. Pre-2026-05-17 the gate only accepted
    ``nos-providers``, which 403'd every operator whose identity (e.g.
    ``akadmin``) was provisioned in ``nos-admins`` instead. Drifts in
    ``default.config.yml`` are caught explicitly because this test
    forces a code change in lock-step.
    """
    src = BASE_PRESENTER.read_text()
    # Find the requireSuperAdmin body
    m = re.search(
        r"protected function requireSuperAdmin\(\)[^{]*\{(.+?)\n\s*\}",
        src, re.DOTALL,
    )
    assert m, "requireSuperAdmin body not parseable"
    body = m.group(1)
    assert "'nos-providers'" in body or '"nos-providers"' in body, (
        "requireSuperAdmin no longer references 'nos-providers' literal"
    )
    assert "'nos-admins'" in body or '"nos-admins"' in body, (
        "requireSuperAdmin no longer references 'nos-admins' literal — "
        "both groups are Tier-1 per CLAUDE.md RBAC table"
    )


def test_post_only_gate_returns_405():
    """``requirePostMethod`` must check the HTTP method is POST and
    raise ``error()`` with status 405 otherwise. Belt-and-suspenders
    against a future maintainer accidentally weakening the gate to a
    silent return."""
    src = BASE_PRESENTER.read_text()
    m = re.search(
        r"protected function requirePostMethod\(\)[^{]*\{(.+?)\}",
        src, re.DOTALL,
    )
    assert m, "requirePostMethod body not parseable"
    body = m.group(1)
    assert "POST" in body and "405" in body, (
        "requirePostMethod weakened — must check POST and error 405"
    )
    assert "$this->error" in body, (
        "requirePostMethod no longer aborts via $this->error — silent return is wrong"
    )


# ── Per-presenter privilege contract ────────────────────────────────


@pytest.mark.parametrize(
    "name,path,actions",
    _PRIVILEGED_PRESENTERS,
    ids=[p[0] for p in _PRIVILEGED_PRESENTERS],
)
def test_privileged_presenter_calls_super_admin_gate(name, path, actions):
    """Privileged presenters MUST be tier-gated — EITHER an explicit
    ``startup()`` calling ``requireSuperAdmin()`` / ``requireGroup()`` /
    ``requireTier()``, OR the declarative ``$minAccessTier = <1..3>`` that
    BasePresenter::startup() enforces by default. The A13.7 incident was a
    presenter that forgot the gate entirely — this test makes that red, while
    allowing both the legacy override and the one-line declarative form.
    """
    src = path.read_text()

    assert _is_tier_gated(src), (
        f"{name} has no RBAC gate — neither a startup() calling "
        f"requireSuperAdmin()/requireGroup()/requireTier() nor a declarative "
        f"$minAccessTier = 1..3. This is the A13.7 regression class: without a "
        f"gate any forward-authed user can call privileged actions."
    )

    # If it DOES override startup(), it must chain parent::startup() (else the
    # base-class edge-trust + tier enforcement never runs).
    body = _startup_body(src)
    if body is not None:
        assert "parent::startup()" in body, (
            f"{name} overrides startup() without parent::startup() — base-class "
            f"edge-trust + minAccessTier enforcement is skipped"
        )


@pytest.mark.parametrize(
    "name,path,actions",
    _PRIVILEGED_PRESENTERS,
    ids=[p[0] for p in _PRIVILEGED_PRESENTERS],
)
def test_state_changing_actions_require_post(name, path, actions):
    """Every state-changing action method MUST call ``requirePostMethod()``
    as its first effective statement — ``<img src=>`` and top-level
    navigations from phishing pages are otherwise vehicles for CSRF."""
    src = path.read_text()
    for action in actions:
        m = re.search(
            rf"public function {action}\([^)]*\)\s*:\s*void\s*\{{(.+?)\n\t\}}",
            src, re.DOTALL,
        )
        assert m, f"{name}::{action} body not parseable"
        body = m.group(1)
        assert "requirePostMethod()" in body, (
            f"{name}::{action} does not call requirePostMethod() — "
            f"GET-based state mutation is exploitable as CSRF / phishing-link."
        )


# ── Latte template contract ─────────────────────────────────────────


_TEMPLATE_PRIVILEGED_PATHS = [
    ("/admin/halt",   TEMPLATES / "Admin"     / "default.latte"),
    ("/admin/resume", TEMPLATES / "Admin"     / "default.latte"),
    # The Inbox answer template uses the plink helper rather than literal
    # paths; the test below scans for any leftover <a href> on Inbox:answer.
]


@pytest.mark.parametrize(
    "path,template",
    _TEMPLATE_PRIVILEGED_PATHS,
    ids=[p[0] for p in _TEMPLATE_PRIVILEGED_PATHS],
)
def test_admin_template_uses_post_form(path, template):
    """The Admin template must trigger halt/resume via a POST form, never
    via ``<a href>``. ``<a href>`` works fine functionally but matches every
    GET-CSRF pattern (image preload, link scanner, top-level navigation)."""
    src = template.read_text()
    # If the path appears, it must be inside a form action= — never inside an a href=.
    href_re = re.compile(rf'<a[^>]*href\s*=\s*["\']?{re.escape(path)}', re.IGNORECASE)
    form_re = re.compile(rf'<form[^>]*method\s*=\s*["\']?post["\']?[^>]*action\s*=\s*["\']?{re.escape(path)}', re.IGNORECASE)
    assert not href_re.search(src), (
        f"{template.name} contains <a href={path}> — A13.7 forbids GET on state-changing actions; "
        f"convert to <form method=\"post\" action=\"{path}\">"
    )
    assert form_re.search(src), (
        f"{template.name} no longer triggers {path} via POST form — regression"
    )


def test_inbox_answer_template_uses_post_forms():
    """Inbox template (successor of A11's Approvals template, retired
    2026-08-08): answering must be a POST form keyed on the question uuid.
    We don't pin the literal path because it goes through Nette's plink
    helper; scan for the pattern instead."""
    src = (TEMPLATES / "Inbox" / "default.latte").read_text()
    # No <a href to Inbox:answer / Inbox:markRead (plink form)
    assert not re.search(r'<a[^>]*href\s*=\s*["\']?\{plink Inbox:(answer|markRead)',
                         src, re.IGNORECASE), (
        "Inbox template uses <a href={plink Inbox:...}> for a state-changing "
        "action — A13.7 forbids; must be "
        "<form method=\"post\" action=\"{plink Inbox:...}\">"
    )
    # MUST have at least one POST form for answer and one for mark-read
    for verb in ("answer", "markRead"):
        assert re.search(
            rf'<form[^>]*method\s*=\s*["\']?post[^>]*action\s*=\s*["\']?\{{plink Inbox:{verb}',
            src, re.IGNORECASE,
        ), f"Inbox template no longer POST-forms the {verb} action"
