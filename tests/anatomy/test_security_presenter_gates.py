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
        "ApprovalsPresenter",
        PRESENTERS / "ApprovalsPresenter.php",
        ["actionApprove", "actionReject"],
    ),
]


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
    ):
        assert helper in src, f"BasePresenter missing helper: {helper}"


def test_super_admin_gate_pins_correct_group():
    """``requireSuperAdmin`` must gate on literal ``nos-providers`` —
    drifts in ``default.config.yml`` are caught explicitly because this
    test forces a code change in lock-step.
    """
    src = BASE_PRESENTER.read_text()
    # Find the requireSuperAdmin body
    m = re.search(
        r"protected function requireSuperAdmin\(\)[^{]*\{(.+?)\}",
        src, re.DOTALL,
    )
    assert m, "requireSuperAdmin body not parseable"
    body = m.group(1)
    assert "'nos-providers'" in body or '"nos-providers"' in body, (
        "requireSuperAdmin no longer gates on 'nos-providers' literal"
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
    """Privileged presenters MUST override ``startup()`` and call the
    ``requireSuperAdmin()`` (or ``requireGroup(...)``) helper. The
    A13.7 incident was a presenter that simply forgot to override
    startup() at all — this test makes that an immediate red CI run.
    """
    src = path.read_text()

    # Must override startup
    assert re.search(r"public function startup\(\)\s*:\s*void", src), (
        f"{name} does not override startup() — privileged presenter must"
    )

    # Locate startup body
    m = re.search(
        r"public function startup\(\)\s*:\s*void\s*\{(.+?)\n\t\}",
        src, re.DOTALL,
    )
    assert m, f"{name} startup() body not parseable"
    body = m.group(1)
    assert "parent::startup()" in body, (
        f"{name} startup() does not call parent::startup() — header parsing breaks"
    )
    assert (
        "requireSuperAdmin()" in body or "requireGroup(" in body
    ), (
        f"{name} startup() does not call requireSuperAdmin() / requireGroup() — "
        f"this is the A13.7 regression class. Without this gate any authenticated "
        f"Authentik user can call privileged actions on this presenter."
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
    # Approvals templates use plink helper rather than literal paths;
    # the test below scans for any leftover <a href> on Approvals.
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


def test_approvals_template_uses_post_forms():
    """Approvals template: actions must be POST forms keyed on actionId.
    We don't pin the literal path because it goes through Nette's plink
    helper; scan for the pattern instead."""
    src = (TEMPLATES / "Approvals" / "default.latte").read_text()
    # No <a href to Approvals:approve / Approvals:reject (plink form)
    assert not re.search(r'<a[^>]*href\s*=\s*["\']?\{plink Approvals:(approve|reject)',
                         src, re.IGNORECASE), (
        "Approvals template uses <a href={plink Approvals:...}> — A13.7 forbids; "
        "must be <form method=\"post\" action=\"{plink Approvals:...}\">"
    )
    # MUST have at least one POST form for approve and one for reject
    for verb in ("approve", "reject"):
        assert re.search(
            rf'<form[^>]*method\s*=\s*["\']?post[^>]*action\s*=\s*["\']?\{{plink Approvals:{verb}',
            src, re.IGNORECASE,
        ), f"Approvals template no longer POST-forms the {verb} action"
