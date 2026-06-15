"""Anatomy CI gate for the plan-choice modal UI (B4b).

Pins the browser-side plan-choice surface that sits between the operator's
"Plan" click and the upgrades_planned queue write:

  1. The browser route ``upgrades/<service>/<recipe>/plan-choice`` →
     ``Upgrades:planChoice`` is registered (before the catch-all ``upgrades/<svc>``
     so Nette's first-match-wins router doesn't swallow 'plan-choice').
  2. ``UpgradesPresenter::actionPlanChoice`` is a CSRF-gated browser action
     (``requirePostMethod()``) that reuses ``planUpgradeWithMode`` and emits the
     ``plan_choice_recorded`` audit event — the same write the bearer API makes.
  3. Both upgrade templates trigger the modal via ``data-action="open-plan-choice"``
     (carrying service / recipe / coexist-supported / target), keep a
     ``<noscript>`` in-place fallback, and load the modal partial + JS.
  4. The JS registers the three data-action verbs and submits the real CSRF
     form (no fetch — preserving the server redirect + flash UX).

Regex-only (no PHP/JS execution) — consistent with test_security_presenter_gates.py,
so the gate runs on the pytest+pyyaml stack.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WING = REPO / "files" / "anatomy" / "wing"
ROUTER = WING / "app" / "Core" / "RouterFactory.php"
PRESENTER = WING / "app" / "Presenters" / "UpgradesPresenter.php"
PARTIAL = WING / "app" / "Templates" / "Upgrades" / "@plan-choice-modal.latte"
DEFAULT_LATTE = WING / "app" / "Templates" / "Upgrades" / "default.latte"
SERVICE_LATTE = WING / "app" / "Templates" / "Upgrades" / "service.latte"
JS = WING / "www" / "assets" / "upgrades-plan-choice.js"


# ── Route ────────────────────────────────────────────────────────────


def test_browser_plan_choice_route_registered():
    src = ROUTER.read_text()
    assert re.search(
        r"addRoute\(\s*['\"]upgrades/<service>/<recipe>/plan-choice['\"]\s*,\s*['\"]Upgrades:planChoice['\"]",
        src,
    ), "browser route upgrades/<service>/<recipe>/plan-choice → Upgrades:planChoice not registered"


def test_plan_choice_route_before_service_catchall():
    """First-match-wins: the plan-choice route must precede the bare
    upgrades/<service> route, else 'plan-choice' is swallowed as a recipe."""
    src = ROUTER.read_text()
    pc = src.find("'upgrades/<service>/<recipe>/plan-choice'")
    svc = src.find("'upgrades/<service>'")
    assert pc != -1 and svc != -1, "plan-choice or upgrades/<service> route missing"
    assert pc < svc, "plan-choice route must come BEFORE upgrades/<service> (first-match-wins)"


# ── Presenter ────────────────────────────────────────────────────────


def _action_body(src: str, action: str) -> str | None:
    m = re.search(
        rf"public function {action}\([^)]*\)\s*:\s*void\s*\{{(.+?)\n\t\}}",
        src, re.DOTALL,
    )
    return m.group(1) if m else None


def test_presenter_has_plan_choice_action():
    body = _action_body(PRESENTER.read_text(), "actionPlanChoice")
    assert body is not None, "UpgradesPresenter::actionPlanChoice not found / not parseable"


def test_plan_choice_action_is_csrf_gated():
    """Browser state mutation → must require POST (CSRF / phishing-link gate),
    same A13.7 contract as actionQueueUpgrade."""
    body = _action_body(PRESENTER.read_text(), "actionPlanChoice")
    assert body and "requirePostMethod()" in body, (
        "actionPlanChoice does not call requirePostMethod() — GET-based mutation is CSRF-exploitable"
    )


def test_plan_choice_action_reuses_plan_upgrade_with_mode():
    """Browser + agent paths must write identical rows — both go through
    UpgradeRepository::planUpgradeWithMode (the plan-choice branch point)."""
    body = _action_body(PRESENTER.read_text(), "actionPlanChoice")
    assert body and "planUpgradeWithMode(" in body, (
        "actionPlanChoice must call planUpgradeWithMode (reuse the bearer API repo path)"
    )


def test_plan_choice_action_does_not_trust_body_identity():
    """planned_by is the forward-auth identity, never a POST field —
    anti-spoof parity with actionQueueUpgrade."""
    body = _action_body(PRESENTER.read_text(), "actionPlanChoice") or ""
    assert "X-Authentik-Username" in body, (
        "actionPlanChoice must derive planned_by from the X-Authentik-Username header, not the body"
    )


def test_plan_choice_emits_audit_event():
    src = PRESENTER.read_text()
    assert "plan_choice_recorded" in src, (
        "actionPlanChoice must emit the plan_choice_recorded audit event"
    )
    # The presenter must actually own an EventRepository to insert it.
    assert "EventRepository" in src and "$this->events->insert(" in src, (
        "UpgradesPresenter must inject EventRepository and insert() the plan_choice_recorded event"
    )


# ── Templates ────────────────────────────────────────────────────────


def test_partial_posts_to_plan_choice_with_csrf():
    src = PARTIAL.read_text()
    assert 'method="post"' in src, "plan-choice modal form must be method=post"
    assert "_csrf" in src and "$csrfToken" in src, "plan-choice modal form missing CSRF token field"
    # Two radio options (a) migration + (b) coexist.
    assert 'value="migration"' in src and 'value="coexist"' in src, (
        "plan-choice modal must offer both migration (a) and coexist (b) radios"
    )
    # The three data-action verbs the JS delegates on.
    for verb in ("close-plan-choice", "submit-plan-choice"):
        assert verb in src, f"plan-choice modal missing data-action={verb}"


def test_no_inline_style_in_partial():
    """Hygiene mirror: the modal partial must not carry an inline <style> block
    (test_wing_ui_hygiene also enforces this repo-wide — pinned here so a B4b
    regression is loud at the feature level too)."""
    assert "<style" not in PARTIAL.read_text(), (
        "plan-choice modal partial has an inline <style> block — move it to upgrades.css"
    )


def _template_wires_modal(path: Path) -> str:
    src = path.read_text()
    assert 'data-action="open-plan-choice"' in src, (
        f"{path.name} Plan control must use data-action=open-plan-choice"
    )
    assert "@plan-choice-modal.latte" in src, f"{path.name} must {{include}} the plan-choice modal partial"
    assert "upgrades-plan-choice.js" in src, f"{path.name} must load upgrades-plan-choice.js"
    # The in-place fallback must survive for JS-off operators.
    assert "<noscript>" in src, f"{path.name} dropped the <noscript> in-place fallback"
    return src


def test_default_template_wires_plan_choice():
    src = _template_wires_modal(DEFAULT_LATTE)
    # Matrix rows lack coexistence_supported → option (b) disabled there.
    assert 'data-coexist-supported="0"' in src, (
        "matrix Plan control must pass data-coexist-supported=0 (recipe rows lack the flag)"
    )


def test_service_template_wires_plan_choice():
    src = _template_wires_modal(SERVICE_LATTE)
    # Per-service recipes carry coexistence_supported → option (b) gated on it.
    assert "coexistence_supported" in src, (
        "service Plan control must gate data-coexist-supported on the recipe's coexistence_supported"
    )


# ── JS ───────────────────────────────────────────────────────────────


def test_js_registers_data_action_verbs():
    src = JS.read_text()
    for verb in ("open-plan-choice", "close-plan-choice", "submit-plan-choice"):
        assert f"'{verb}'" in src or f'"{verb}"' in src, f"upgrades-plan-choice.js missing case {verb}"


def test_js_submits_real_form_not_fetch():
    """Design constraint: submit the real CSRF <form> (server redirect+flash UX),
    not a fetch/XHR. Assert the form submit path exists and no fetch() is used."""
    src = JS.read_text()
    assert ".submit()" in src, "upgrades-plan-choice.js must submit the real form (form.submit())"
    assert "fetch(" not in src, (
        "upgrades-plan-choice.js must NOT use fetch — submit the CSRF form to preserve redirect+flash"
    )
