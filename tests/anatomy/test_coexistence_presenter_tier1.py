"""Anatomy CI gate for the B4c RBAC fix + 2x-toggle / drafts UI.

The maps flagged that ``CoexistencePresenter`` and ``MigrationsPresenter``
shipped with NO ``$minAccessTier`` — an UNGATED browser view that any
forward-authed identity (incl. tier-4 ``nos-guests``) could read. B4c adds the
browser mutators (toggle-as-primary / deactivate-secondary / cancel-queued on
coexistence; mark-reviewed / mark-rejected on migrations), so both presenters
MUST become Tier-1 — parity with ``UpgradesPresenter`` (the same A13.7
declarative-gate contract enforced by ``BasePresenter::startup()``).

Core contract (the step's named gate):
  * CoexistencePresenter declares ``$minAccessTier = 1``.
  * MigrationsPresenter   declares ``$minAccessTier = 1``.

Plus the load-bearing surface this RBAC gate protects, so a regression that
drops the mutators (and silently makes the gate vacuous) is also red:
  * the three coexistence browser actions + the two migration review actions are
    CSRF-gated (``requirePostMethod()``);
  * the browser routes are registered, specific-before-catch-all;
  * the matrix emits the 2x coexist rows + the /migrations Proposed column +
    the per-service Proposals strip surface the local-forge MR link.

Regex-only (no PHP execution) — consistent with test_security_presenter_gates.py
and test_plan_choice_ui.py, so it runs on the pytest+pyyaml stack.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WING = REPO / "files" / "anatomy" / "wing"
PRESENTERS = WING / "app" / "Presenters"
COEX_PRESENTER = PRESENTERS / "CoexistencePresenter.php"
MIG_PRESENTER = PRESENTERS / "MigrationsPresenter.php"
UPG_PRESENTER = PRESENTERS / "UpgradesPresenter.php"
ROUTER = WING / "app" / "Core" / "RouterFactory.php"
UPG_REPO = WING / "app" / "Model" / "UpgradeRepository.php"
COEX_LATTE = WING / "app" / "Templates" / "Coexistence" / "default.latte"
MIG_LATTE = WING / "app" / "Templates" / "Migrations" / "default.latte"
UPG_SERVICE_LATTE = WING / "app" / "Templates" / "Upgrades" / "service.latte"
UPG_DEFAULT_LATTE = WING / "app" / "Templates" / "Upgrades" / "default.latte"
JS = WING / "www" / "assets" / "widget-cutover-confirm.js"

_TIER1_RE = re.compile(r"\$minAccessTier\s*=\s*1\s*;")


def _action_body(src: str, action: str) -> str | None:
    m = re.search(
        rf"public function {action}\([^)]*\)\s*:\s*void\s*\{{(.+?)\n\t\}}",
        src, re.DOTALL,
    )
    return m.group(1) if m else None


# ── Core contract: the Tier-1 RBAC gate ─────────────────────────────


def test_coexistence_presenter_is_tier1():
    """CoexistencePresenter MUST declare $minAccessTier = 1 — the one-line
    declarative gate BasePresenter::startup() enforces. Was UNGATED."""
    assert _TIER1_RE.search(COEX_PRESENTER.read_text()), (
        "CoexistencePresenter no longer declares `$minAccessTier = 1` — the "
        "/coexistence view + toggle mutators are UNGATED (A13.7 regression class)."
    )


def test_migrations_presenter_is_tier1():
    """MigrationsPresenter MUST declare $minAccessTier = 1 — the Proposed column
    exposes agent-authored drafts + review controls. Was UNGATED."""
    assert _TIER1_RE.search(MIG_PRESENTER.read_text()), (
        "MigrationsPresenter no longer declares `$minAccessTier = 1` — the "
        "/migrations Proposed column + review mutators are UNGATED."
    )


def test_neither_presenter_overrides_startup_without_parent():
    """If either presenter DOES override startup(), it must chain
    parent::startup() (else the declarative gate never runs). The B4c design
    uses the property, not an override — this catches a future override slip."""
    for path in (COEX_PRESENTER, MIG_PRESENTER):
        src = path.read_text()
        m = re.search(r"public function startup\(\)\s*:\s*void\s*\{(.+?)\n\t\}", src, re.DOTALL)
        if m is not None:
            assert "parent::startup()" in m.group(1), (
                f"{path.name} overrides startup() without parent::startup() — "
                f"base-class minAccessTier enforcement is skipped"
            )


# ── Coexistence browser mutators ────────────────────────────────────


def test_coexistence_browser_actions_present_and_csrf_gated():
    src = COEX_PRESENTER.read_text()
    for action in ("actionTogglePrimary", "actionDeactivateSecondary", "actionCancel"):
        body = _action_body(src, action)
        assert body is not None, f"CoexistencePresenter::{action} not found / not parseable"
        assert "requirePostMethod()" in body, (
            f"CoexistencePresenter::{action} does not call requirePostMethod() — "
            f"GET-based state mutation is CSRF-exploitable"
        )


def test_toggle_commits_non_dry_run():
    """The operator toggle is the committed cutover — promote() must be called
    with dry_run=false (the second positional arg)."""
    body = _action_body(COEX_PRESENTER.read_text(), "actionTogglePrimary") or ""
    assert "promote(" in body and "false" in body, (
        "actionTogglePrimary must commit via promote(..., false) (dry_run=false)"
    )


def test_cancel_derives_identity_from_header_not_body():
    """cancelled_by is the forward-auth identity, never a POST field —
    anti-spoof parity with UpgradesPresenter."""
    body = _action_body(COEX_PRESENTER.read_text(), "actionCancel") or ""
    assert "X-Authentik-Username" in body, (
        "actionCancel must derive cancelled_by from X-Authentik-Username, not the body"
    )


# ── Migrations review mutators ──────────────────────────────────────


def test_migration_review_actions_present_and_csrf_gated():
    src = MIG_PRESENTER.read_text()
    for action in ("actionMarkReviewed", "actionMarkRejected"):
        body = _action_body(src, action)
        assert body is not None, f"MigrationsPresenter::{action} not found / not parseable"
        assert "requirePostMethod()" in body, (
            f"MigrationsPresenter::{action} does not call requirePostMethod()"
        )


def test_migrations_proposed_column_data_sourced():
    """The Proposed column reads agent drafts via listReviewable()."""
    src = MIG_PRESENTER.read_text()
    assert "MigrationAuthoredRepository" in src and "listReviewable()" in src, (
        "MigrationsPresenter must inject MigrationAuthoredRepository and read "
        "listReviewable() for the Proposed column"
    )


def test_migrations_never_sets_merged_in_wing():
    """GATE 2: Wing only ever flips in_review / rejected; merged is the forge's
    exclusive write. The presenter must not pass 'merged' to setReviewStatus."""
    src = MIG_PRESENTER.read_text()
    assert "setReviewStatus($id, 'merged'" not in src and 'setReviewStatus($id, "merged"' not in src, (
        "MigrationsPresenter must NOT flip a proposal to 'merged' — that's the forge webhook's write (GATE 2)"
    )


# ── Routes (specific-before-catch-all) ──────────────────────────────


def test_coexistence_browser_routes_registered():
    src = ROUTER.read_text()
    for path, target in (
        ("coexistence/<service>/toggle-primary", "Coexistence:togglePrimary"),
        ("coexistence/<service>/deactivate-secondary", "Coexistence:deactivateSecondary"),
        ("coexistence/<service>/cancel", "Coexistence:cancel"),
    ):
        assert re.search(
            rf"addRoute\(\s*['\"]{re.escape(path)}['\"]\s*,\s*['\"]{re.escape(target)}['\"]",
            src,
        ), f"browser route {path} -> {target} not registered"


def test_coexistence_verbs_before_catchall():
    src = ROUTER.read_text()
    cancel = src.find("'coexistence/<service>/cancel'")
    catchall = src.rfind("'coexistence'")
    assert cancel != -1 and catchall != -1, "coexistence verb or catch-all route missing"
    assert cancel < catchall, (
        "coexistence verb routes must precede the bare 'coexistence' catch-all (first-match-wins)"
    )


def test_migration_review_routes_before_detail():
    src = ROUTER.read_text()
    for path, target in (
        ("migrations/<id>/mark-reviewed", "Migrations:markReviewed"),
        ("migrations/<id>/mark-rejected", "Migrations:markRejected"),
    ):
        assert re.search(
            rf"addRoute\(\s*['\"]{re.escape(path)}['\"]\s*,\s*['\"]{re.escape(target)}['\"]",
            src,
        ), f"browser route {path} -> {target} not registered"
    reviewed = src.find("'migrations/<id>/mark-reviewed'")
    detail = src.find("'migrations/<id>'")
    assert reviewed != -1 and detail != -1, "mark-reviewed or detail route missing"
    assert reviewed < detail, (
        "mark-reviewed/mark-rejected must precede migrations/<id> (first-match-wins)"
    )


# ── Matrix 2x rows + deep-link ──────────────────────────────────────


def test_matrix_emits_coexist_rows():
    """UpgradeRepository::matrix() doubles a coexisting service into role rows."""
    src = UPG_REPO.read_text()
    assert "coexist_role" in src and "coexistenceTracksByService" in src, (
        "matrix() must emit coexist_role rows from coexistenceTracksByService()"
    )


def test_matrix_template_renders_role_badge_and_deeplink():
    src = UPG_DEFAULT_LATTE.read_text()
    assert "coexist_role" in src, "default.latte must render the coexist role badge"
    assert "/coexistence#" in src, (
        "matrix row must deep-link to /coexistence#<service> (the toggle source of truth)"
    )


# ── Coexistence template: primary/secondary pair + queued + cancel ──


def test_coexistence_template_renders_pair_and_queue():
    src = COEX_LATTE.read_text()
    assert "coex-pair" in src, "Coexistence template missing the primary/secondary pair block"
    assert 'data-action="toggle-primary"' in src, "missing toggle-primary control"
    assert 'data-action="deactivate-secondary"' in src, "missing deactivate-secondary control"
    assert "coex-queued" in src and 'data-action="cancel-coexist"' in src, (
        "Coexistence template must surface the queued rows with a Cancel control (listPlanned gap #4)"
    )
    # The toggle/deactivate/cancel mutate state → must be POST forms with CSRF.
    assert 'method="post"' in src and "$csrfToken" in src, (
        "Coexistence template mutators must post a CSRF form (A13.7), not <a href>"
    )


# ── Proposals strip = the MR-link surface ───────────────────────────


def test_service_template_has_proposals_strip_with_mr_link():
    src = UPG_SERVICE_LATTE.read_text()
    assert "mig-proposed-strip" in src or "drafts" in src, (
        "service.latte must render the Proposals strip (agent drafts)"
    )
    assert "mr_url" in src and "Review MR" in src, (
        "Proposals strip must surface the local-forge Review MR link (the first MR link in the UI)"
    )


def test_migrations_template_proposed_column_has_mr_link():
    src = MIG_LATTE.read_text()
    assert "mig-col-proposed" in src, "/migrations must add the Proposed (agent drafts) column"
    assert "mr_url" in src and "Review MR" in src, (
        "Proposed column must surface the local-forge Review MR link"
    )
    # mark-reviewed / mark-rejected POST forms (operator never merges in Wing).
    assert "Migrations:markReviewed" in src and "Migrations:markRejected" in src, (
        "Proposed column must POST-form the mark-reviewed / mark-rejected verbs"
    )


# ── JS verbs ────────────────────────────────────────────────────────


def test_js_registers_toggle_verbs():
    src = JS.read_text()
    for verb in ("toggle-primary", "confirm-toggle", "deactivate-secondary", "cancel-coexist"):
        assert f"'{verb}'" in src or f'"{verb}"' in src, (
            f"widget-cutover-confirm.js missing data-action case {verb}"
        )
    # The operator-path verbs submit the real CSRF form (server redirect+flash),
    # NOT a fetch — the typed-PRIMARY toggle posts coex-toggle-form.
    assert "coex-toggle-form" in src and ".submit()" in src, (
        "toggle/deactivate/cancel must submit the real CSRF form (form.submit())"
    )


# ── A5 (§6.6): rollback one-click vs forward typed-confirm ───────────


def test_presenter_flags_rollback_target():
    """renderDefault() derives is_rollback_target from the demoted_from_primary_at
    stamp (round-tripped via Bone /api/coexistence). That single field — not a
    version-string heuristic — is how the template knows which secondary is the
    one-click rollback target."""
    src = COEX_PRESENTER.read_text()
    assert "is_rollback_target" in src, (
        "CoexistencePresenter must set is_rollback_target on each secondary"
    )
    assert "demoted_from_primary_at" in src, (
        "is_rollback_target must derive from demoted_from_primary_at (the "
        "promote_track stamp), not a version heuristic"
    )
    # Must be derived from the stamp's presence, not hard-coded true.
    assert re.search(
        r"is_rollback_target['\"]\]\s*=\s*!empty\(\$[A-Za-z_]+\['demoted_from_primary_at'\]\)",
        src,
    ), "is_rollback_target must be !empty($t['demoted_from_primary_at'])"


def test_template_splits_forward_and_rollback_controls():
    """The secondary card branches on is_rollback_target: a rollback-primary
    one-click button for the demoted prior primary, the typed-confirm
    toggle-primary button for every other secondary."""
    src = COEX_LATTE.read_text()
    assert 'data-action="rollback-primary"' in src, (
        "Coexistence template missing the one-click rollback-primary control"
    )
    assert 'data-action="toggle-primary"' in src, (
        "Coexistence template must keep the typed-confirm toggle-primary control"
    )
    # The two controls must be mutually-exclusive on the is_rollback_target flag.
    assert "is_rollback_target" in src, (
        "the rollback vs toggle split must branch on $track['is_rollback_target']"
    )
    # rollback branch comes after the is_rollback_target test (inside it).
    flag_idx = src.find("is_rollback_target")
    rollback_idx = src.find('data-action="rollback-primary"')
    assert flag_idx != -1 and rollback_idx != -1 and flag_idx < rollback_idx, (
        "rollback-primary must render inside the is_rollback_target branch"
    )


def test_rollback_is_one_click_forward_is_typed():
    """Rollback (onRollback) is a single window.confirm posting the SAME shared
    coex-toggle-form — NOT the typed TOGGLE_PHRASE modal. The forward path keeps
    the typed-PRIMARY modal. The asymmetry is purely client-side confirm friction
    inverted to match risk."""
    src = JS.read_text()
    # rollback-primary delegated.
    assert "'rollback-primary'" in src or '"rollback-primary"' in src, (
        "widget-cutover-confirm.js missing the rollback-primary data-action case"
    )
    # onRollback exists, uses window.confirm (one-click) + the shared toggle form.
    m = re.search(r"function onRollback\(btn\)\s*\{(.+?)\n\t\}", src, re.DOTALL)
    assert m, "onRollback(btn) function not found"
    body = m.group(1)
    assert "window.confirm" in body, (
        "onRollback must be a single window.confirm (one-click), not a typed modal"
    )
    assert "coex-toggle-form" in body, (
        "onRollback must submit the SAME shared coex-toggle-form (same endpoint)"
    )
    assert "TOGGLE_PHRASE" not in body, (
        "onRollback must NOT use the typed TOGGLE_PHRASE — rollback is one-click"
    )
    # Forward path still pins the typed phrase constant.
    assert "const TOGGLE_PHRASE = 'PRIMARY'" in src, (
        "the forward toggle must keep the typed-PRIMARY confirm (TOGGLE_PHRASE)"
    )
