"""Anatomy CI gate — Phase 2 plan-choice DISRUPTION-PREVIEW UI surface.

Mirrors test_plan_choice_ui.py (the F1 coexistence-modal gate) for the
disruption-preview half of docs/archive/upgrade-reset-scope-and-session-safety.md
(§"Wing /upgrades surface", §"Run mode"). The write path (presenter + repo
columns) is pinned by test_plan_choice_run_mode.py; this gate pins the
operator-facing modal:

  1. The modal partial exposes a disruption-preview badge region + a session-risk
     warning callout + a run_mode radio group (Detached / Attached, plus the
     host_reboot-only "Stage, then reboot"), and a hidden run_mode input seeded
     'attached'.
  2. Both trigger templates thread the recipe's reset scope via data-* (mirroring
     data-coexist-supported) — data-session-risk / data-reset-scope /
     data-estimated-sec / data-affected-services / data-affected-host-apps /
     data-reset-reason.
  3. The JS reads those data-*, renders the badge, gates the run_mode group on
     session risk (present-when-risk, absent-otherwise), and syncs the hidden
     run_mode input before submitting the real CSRF form.

Regex/substring only (no PHP/JS execution) — consistent with test_plan_choice_ui.py.
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WING = REPO / "files" / "anatomy" / "wing"
PARTIAL = WING / "app" / "Templates" / "Upgrades" / "@plan-choice-modal.latte"
DEFAULT_LATTE = WING / "app" / "Templates" / "Upgrades" / "default.latte"
SERVICE_LATTE = WING / "app" / "Templates" / "Upgrades" / "service.latte"
JS = WING / "www" / "assets" / "upgrades-plan-choice.js"

# The trigger-button data-* attributes that thread the reset scope into the modal.
RESET_DATA_ATTRS = (
    "data-session-risk",
    "data-reset-scope",
    "data-estimated-sec",
    "data-affected-services",
    "data-affected-host-apps",
    "data-reset-reason",
)


# ── Modal partial ────────────────────────────────────────────────────


def test_partial_has_disruption_badge():
    """A scope badge region the JS fills with a human label + ~estimate."""
    src = PARTIAL.read_text()
    assert 'id="plan-choice-disruption-badge"' in src, (
        "plan-choice modal missing the disruption badge (#plan-choice-disruption-badge)"
    )
    assert 'id="plan-choice-disruption"' in src, (
        "plan-choice modal missing the disruption-preview panel"
    )


def test_partial_has_session_risk_warning():
    """A warning callout that the JS unhides for session-risky scopes."""
    src = PARTIAL.read_text()
    assert 'id="plan-choice-session-warning"' in src, (
        "plan-choice modal missing the session-risk warning callout"
    )
    assert "disconnect" in src.lower(), (
        "session-risk warning must tell the operator the session can disconnect"
    )


def test_partial_hidden_run_mode_input_defaults_attached():
    """The hidden run_mode input posts 'attached' by default (non-session-risk
    recipes never touch the radio — they post attached implicitly)."""
    src = PARTIAL.read_text()
    assert 'name="run_mode" id="plan-choice-runmode" value="attached"' in src, (
        "plan-choice modal missing hidden run_mode input defaulting to 'attached'"
    )


def test_partial_has_run_mode_radio_group():
    """A run_mode radio group with detached (default) + attached, plus the
    host_reboot-only stage_then_reboot option; the fieldset ships hidden (JS
    unhides it only for session-risk)."""
    src = PARTIAL.read_text()
    assert 'id="plan-choice-runmode-fieldset"' in src, "run_mode fieldset missing"
    # The fieldset is hidden by default — only session-risk unhides it.
    fieldset_open = src.index('id="plan-choice-runmode-fieldset"')
    fieldset_tag = src[src.rfind("<fieldset", 0, fieldset_open):fieldset_open + 80]
    assert "hidden" in fieldset_tag, (
        "run_mode fieldset must ship hidden (only session-risk unhides it)"
    )
    for val in ("attached", "detached", "stage_then_reboot"):
        assert f'value="{val}"' in src, f"run_mode radio missing value={val}"
    # detached is the recommended default radio.
    assert 'value="detached" id="plan-choice-runmode-detached" checked' in src, (
        "detached must be the default-checked run_mode radio (recommended)"
    )
    # The stage_then_reboot label is hidden until JS unhides it for host_reboot.
    stage = src.index('id="plan-choice-runmode-stage-label"')
    stage_tag = src[src.rfind("<label", 0, stage):src.index(">", stage)]
    assert "hidden" in stage_tag, (
        "stage_then_reboot option must ship hidden (host_reboot scope only)"
    )


def test_partial_radio_group_name_is_separate_from_submitted_field():
    """The radios use a UI-only name (plan_runmode_radio) the JS mirrors into the
    hidden run_mode field — same pattern as plan_choice_radio → plan_mode."""
    src = PARTIAL.read_text()
    assert 'name="plan_runmode_radio"' in src, (
        "run_mode radios must use the UI-only name plan_runmode_radio"
    )


# ── Trigger templates thread the reset scope ─────────────────────────


def _assert_trigger_threads_reset(path: Path) -> str:
    src = path.read_text()
    for attr in RESET_DATA_ATTRS:
        assert attr in src, f"{path.name} Plan control must carry {attr}"
    return src


def test_default_template_threads_reset_scope():
    src = _assert_trigger_threads_reset(DEFAULT_LATTE)
    # Keyed off the matrix row ($row) — same channel as data-coexist-supported.
    assert "$row['session_risk']" in src, (
        "matrix Plan control must gate data-session-risk on the row's session_risk"
    )
    assert "$row['reset_scope']" in src, (
        "matrix Plan control must carry the row's reset_scope"
    )
    assert "$row['reset']['estimated_sec']" in src, (
        "matrix Plan control must carry the row's reset estimated_sec"
    )


def test_service_template_threads_reset_scope():
    src = _assert_trigger_threads_reset(SERVICE_LATTE)
    # Keyed off the per-recipe row ($r).
    assert "$r['session_risk']" in src, (
        "service Plan control must gate data-session-risk on the recipe's session_risk"
    )
    assert "$r['reset_scope']" in src, (
        "service Plan control must carry the recipe's reset_scope"
    )


# ── JS ───────────────────────────────────────────────────────────────


def test_js_reads_reset_data_attrs():
    src = JS.read_text()
    for ds in ("sessionRisk", "resetScope", "estimatedSec", "affectedServices",
               "affectedHostApps", "resetReason"):
        assert f"dataset.{ds}" in src, f"upgrades-plan-choice.js must read btn.dataset.{ds}"


def test_js_gates_run_mode_on_session_risk():
    """setSessionRisk(risk) toggles the warning + run_mode fieldset hidden state —
    present-when-risk, absent-otherwise."""
    src = JS.read_text()
    assert "setSessionRisk" in src, "JS must have a setSessionRisk gate helper"
    assert "runModeFieldset.hidden = !risk" in src, (
        "run_mode fieldset must be unhidden ONLY for session-risk scopes"
    )
    assert "sessionWarning.hidden = !risk" in src, (
        "session warning must be unhidden ONLY for session-risk scopes"
    )


def test_js_stage_option_only_for_host_reboot():
    """The stage_then_reboot option is unhidden only for the host_reboot scope."""
    src = JS.read_text()
    assert "scope === 'host_reboot'" in src, (
        "stage_then_reboot must be gated on the host_reboot scope"
    )


def test_js_syncs_run_mode_before_submit():
    """syncRunMode() runs before form.submit(), and defaults to 'attached' when
    the radio group is absent/hidden (non-session-risk)."""
    src = JS.read_text()
    assert "syncRunMode" in src, "JS must have a syncRunMode helper"
    # Default-attached fallback when the fieldset is hidden.
    assert "this.runModeInput.value = 'attached'" in src, (
        "syncRunMode must default the hidden run_mode input to 'attached' when hidden"
    )
    # submit() syncs both plan_mode + run_mode before posting the real form.
    submit = src[src.index("submit() {"):]
    submit = submit[:submit.index("}")]
    assert "syncRunMode()" in submit, "submit() must call syncRunMode() before form.submit()"
    assert ".submit()" in submit, "submit() must still post the real CSRF form"


def test_js_renders_disruption_badge():
    """open() renders the badge via renderDisruption (scope label + estimate)."""
    src = JS.read_text()
    assert "renderDisruption" in src, "JS must render the disruption badge"
    assert "scopeLabel" in src and "estimateLabel" in src, (
        "JS must build a human scope label + estimate for the badge"
    )
