"""Anatomy CI gate — devlog event types whitelisted on BOTH event sides.

The devlog write path POSTs through Bone (devlog_lib.emit_bone_event), so a
missing whitelist entry turns the audit write into a silent 400 — the exact
failure mode of the 2026-05-17 remediator incident. Wing's EventsPresenter
validates against EventRepository::VALID_TYPES (by-construction alignment),
so the two sources that must agree are Bone's events.py and the PHP constant.
"""
from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
BONE = REPO / "files/anatomy/bone/events.py"
PHP_REPO = REPO / "files/anatomy/wing/app/Model/EventRepository.php"
PHP_PRESENTER = REPO / "files/anatomy/wing/app/Presenters/Api/EventsPresenter.php"

DEVLOG_TYPES = (
    "devlog_entry_created",
    "devlog_entry_updated",
    "devlog_entry_deleted",
    "devlog_sync_run",
    "devlog_published",
)

# ── Agentic upgrade→migration→coexistence epic — 8 new types (Phase B / B1) ──
# Same twin-parity contract as DEVLOG_TYPES: every type below MUST appear in
# BOTH Bone's events.py VALID_TYPES and Wing's EventRepository::VALID_TYPES, or
# an agent's Bone-proxied POST silently 400s (the 2026-05-17 remediator_report
# incident). See docs/archive/agentic-upgrade-migration-coexistence-design.md §2.6.
UPGRADE_COEXIST_B1_TYPES = (
    "plan_choice_recorded",
    "migration_authored",
    "migration_pr_opened",
    "migration_promoted",
    "migration_rejected",
    "coexistence_promote",
    "coexistence_demote",
    "coexistence_cancel",
)

# ── Pre-existing drift backfilled in B1 (Wing carried these; Bone did not) ──
# The migration-author emits through AgentKit (agent_session_*…) when run via
# the runtime, and those traverse Bone. B1 backfills the AgentKit + patch_* +
# approval + admin-emergency + e2e families into Bone so the migration-author's
# session events don't 400. This gate pins that the backfill stays in BOTH twins.
B1_BACKFILL_TYPES = (
    "patch_start", "patch_step_ok", "patch_step_failed", "patch_end",
    "agent_session_start", "agent_session_end",
    "agent_thread_start", "agent_thread_end",
    "agent_iteration_start", "agent_iteration_end",
    "agent_tool_use", "agent_tool_result",
    "agent_message", "agent_grader_decision",
    "agent_webhook_dispatch", "agent_webhook_receipt",
    "agent_vault_resolved",
    "agent_approval_request", "agent_approval_decision",
    "admin_emergency_halt", "admin_emergency_resume",
    "e2e_journey_start", "e2e_journey_step", "e2e_journey_end",
)

# ── A3 (Q5/2026-06-16): Wing "Promote to migration" Tier-1 button ───────────
# The operator's supervision event for the button press
# (UpgradesPresenter::emitPromoteRequested). Same NON-NEGOTIABLE twin-parity
# contract: must be in BOTH Bone's events.py VALID_TYPES and Wing's
# EventRepository::VALID_TYPES, else a Bone-proxied replay/forward of the row
# 400s. See docs/archive/agentic-upgrade-adjustments-design.md §4.5.
A3_PROMOTE_BUTTON_TYPES = (
    "migration_promote_requested",
)

# ── A4 (Q3/2026-06-16): manual re-runnable "Copy data" action ───────────────
# The relocated B5 data move (Api\CoexistencePresenter::actionCopyData, emitted
# only on a committed copy: dry_run=false AND Bone 2xx). Same NON-NEGOTIABLE
# twin-parity contract: must be in BOTH Bone's events.py VALID_TYPES and Wing's
# EventRepository::VALID_TYPES, else a Bone-proxied replay/forward of the row
# 400s. See docs/archive/agentic-upgrade-adjustments-design.md §5.4.
A4_COPY_DATA_TYPES = (
    "coexistence_copy_data",
)

# ── F3 (2026-06-18): Unqueue / Cancel a planned upgrade (Tier-1) ─────────────
# The operator's supervision event for the "Unqueue" control on a planned
# upgrade row (UpgradesPresenter::emitUpgradeUnqueued — the machinery path to
# reset a queued upgrade and re-run the plan-choice flow for a re-test). Same
# NON-NEGOTIABLE twin-parity contract: must be in BOTH Bone's events.py
# VALID_TYPES and Wing's EventRepository::VALID_TYPES, else a Bone-proxied
# replay/forward of the row 400s (the 2026-05-17 remediator incident class).
F3_UNQUEUE_TYPES = (
    "upgrade_unqueued",
)


def test_bone_whitelists_devlog_types():
    src = BONE.read_text(encoding="utf-8")
    for t in DEVLOG_TYPES:
        assert f'"{t}"' in src, f"Bone VALID_TYPES missing {t}"


def test_wing_repository_whitelists_devlog_types():
    src = PHP_REPO.read_text(encoding="utf-8")
    for t in DEVLOG_TYPES:
        assert f"'{t}'" in src, f"Wing EventRepository VALID_TYPES missing {t}"


def test_presenter_validates_via_repository_constant():
    # The third surface stays aligned by construction — pin that it still
    # references the shared constant instead of growing its own list.
    src = PHP_PRESENTER.read_text(encoding="utf-8")
    assert re.search(r"EventRepository::VALID_TYPES", src), (
        "EventsPresenter no longer validates via EventRepository::VALID_TYPES — "
        "devlog types must be added to its own whitelist too"
    )


def test_bone_whitelists_b1_upgrade_coexist_types():
    """The 8 new B1 event types are all present in Bone's VALID_TYPES."""
    src = BONE.read_text(encoding="utf-8")
    for t in UPGRADE_COEXIST_B1_TYPES:
        assert f'"{t}"' in src, f"Bone VALID_TYPES missing B1 type {t}"


def test_wing_repository_whitelists_b1_upgrade_coexist_types():
    """The 8 new B1 event types are all present in Wing's VALID_TYPES (twin)."""
    src = PHP_REPO.read_text(encoding="utf-8")
    for t in UPGRADE_COEXIST_B1_TYPES:
        assert f"'{t}'" in src, f"Wing EventRepository VALID_TYPES missing B1 type {t}"


def test_b1_backfill_types_present_in_both_twins():
    """The AgentKit/patch_*/approval/admin/e2e drift backfilled by B1 is in BOTH
    twins — without it the migration-author's AgentKit session events 400 at Bone.
    """
    bone = BONE.read_text(encoding="utf-8")
    php = PHP_REPO.read_text(encoding="utf-8")
    for t in B1_BACKFILL_TYPES:
        assert f'"{t}"' in bone, f"Bone VALID_TYPES missing backfill type {t}"
        assert f"'{t}'" in php, f"Wing EventRepository VALID_TYPES missing backfill type {t}"


def test_a3_promote_button_type_present_in_both_twins():
    """A3 (Q5): the operator's `migration_promote_requested` supervision event for
    the "Promote to migration" button is in BOTH twins. UpgradesPresenter emits it
    Wing-side; the twin keeps a Bone-proxied replay/forward of the row from 400'ing
    (the 2026-05-17 remediator incident class). One-commit twin rule.
    """
    bone = BONE.read_text(encoding="utf-8")
    php = PHP_REPO.read_text(encoding="utf-8")
    for t in A3_PROMOTE_BUTTON_TYPES:
        assert f'"{t}"' in bone, f"Bone VALID_TYPES missing A3 type {t}"
        assert f"'{t}'" in php, f"Wing EventRepository VALID_TYPES missing A3 type {t}"


def test_a4_copy_data_type_present_in_both_twins():
    """A4 (Q3): the `coexistence_copy_data` audit event for the manual,
    re-runnable "Copy data" action is in BOTH twins. Api\\CoexistencePresenter
    emits it Wing-side on a committed copy; the twin keeps a Bone-proxied
    replay/forward of the row from 400'ing (the 2026-05-17 remediator incident
    class). One-commit twin rule.
    """
    bone = BONE.read_text(encoding="utf-8")
    php = PHP_REPO.read_text(encoding="utf-8")
    for t in A4_COPY_DATA_TYPES:
        assert f'"{t}"' in bone, f"Bone VALID_TYPES missing A4 type {t}"
        assert f"'{t}'" in php, f"Wing EventRepository VALID_TYPES missing A4 type {t}"


def test_a4_copy_data_presenter_emits_the_twinned_type():
    """The emitter and the whitelist agree: Api\\CoexistencePresenter emits
    exactly the `coexistence_copy_data` type the twins whitelist, ONLY on a
    committed move (catches a future rename / a drift between emitter + whitelist).
    """
    presenter = (
        REPO / "files/anatomy/wing/app/Presenters/Api/CoexistencePresenter.php"
    ).read_text(encoding="utf-8")
    for t in A4_COPY_DATA_TYPES:
        assert f"'{t}'" in presenter, (
            f"Api\\CoexistencePresenter no longer emits {t} — emitter/whitelist drift"
        )


def test_a3_promote_presenter_emits_the_twinned_type():
    """The emitter and the whitelist agree: UpgradesPresenter emits exactly the
    `migration_promote_requested` type the twins whitelist (catches a future rename
    on one side only — the emitter or the whitelist drifting apart)."""
    presenter = (
        REPO / "files/anatomy/wing/app/Presenters/UpgradesPresenter.php"
    ).read_text(encoding="utf-8")
    for t in A3_PROMOTE_BUTTON_TYPES:
        assert f"'{t}'" in presenter, (
            f"UpgradesPresenter no longer emits {t} — emitter/whitelist drift"
        )


def test_f3_unqueue_type_present_in_both_twins():
    """F3: the operator's `upgrade_unqueued` supervision event for the "Unqueue"
    control on a planned upgrade is in BOTH twins. UpgradesPresenter emits it
    Wing-side; the twin keeps a Bone-proxied replay/forward of the row from
    400'ing (the 2026-05-17 remediator incident class). One-commit twin rule.
    """
    bone = BONE.read_text(encoding="utf-8")
    php = PHP_REPO.read_text(encoding="utf-8")
    for t in F3_UNQUEUE_TYPES:
        assert f'"{t}"' in bone, f"Bone VALID_TYPES missing F3 type {t}"
        assert f"'{t}'" in php, f"Wing EventRepository VALID_TYPES missing F3 type {t}"


def test_f3_unqueue_presenter_emits_the_twinned_type():
    """The emitter and the whitelist agree: UpgradesPresenter emits exactly the
    `upgrade_unqueued` type the twins whitelist (catches a future rename on one
    side only — the emitter or the whitelist drifting apart)."""
    presenter = (
        REPO / "files/anatomy/wing/app/Presenters/UpgradesPresenter.php"
    ).read_text(encoding="utf-8")
    for t in F3_UNQUEUE_TYPES:
        assert f"'{t}'" in presenter, (
            f"UpgradesPresenter no longer emits {t} — emitter/whitelist drift"
        )


def test_emitters_use_whitelisted_types():
    lib = (REPO / "files/anatomy/scripts/devlog_lib.py").read_text(encoding="utf-8")
    sync = (REPO / "files/anatomy/scripts/devlog-sync.py").read_text(encoding="utf-8")
    post = (REPO / "tools/devlog-post.py").read_text(encoding="utf-8")
    assert '"devlog_sync_run"' in sync
    assert '"devlog_entry_updated"' in post and '"devlog_entry_created"' in post
    assert 'ACTOR_ID = "agent:devlog"' in lib
