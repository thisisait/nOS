"""Event ingestion — HMAC validator + delegate to clients/wing.py.

Bone offers this as a convenience for the callback plugin (which prefers
HTTP → SQLite fallback). The plugin signs each request so that even if
Bone is behind nginx and exposed on a socket, a rogue script can't inject
fake events.

Anatomy P0.1b (2026-05-04): direct sqlite3 access moved to
``files/anatomy/bone/clients/wing.py``. This module now does HMAC
validation + payload sanity check + delegates the actual INSERT to
the centralized client. CI lint forbids ``sqlite3.connect.*wing\\.db``
outside ``bone/clients/wing.py`` so the seam stays single.
"""

from __future__ import annotations

import hmac
import os
import time
from typing import Any

from clients import wing as _wing  # noqa: E402  — relative import after sys.path setup

HMAC_SECRET = os.getenv("WING_EVENTS_HMAC_SECRET", "")

# Backward-compat aliases — existing imports use ``events.WING_DB`` and
# ``events.WingDBNotReady``. Re-export them from the centralized
# clients/wing.py module so callers don't need to change imports.
WING_DB = _wing._wing_db_path()
WingDBNotReady = _wing.WingDBNotReady

VALID_TYPES = {
    "playbook_start", "playbook_end",
    "play_start", "play_end",
    "task_start", "task_ok", "task_changed", "task_failed",
    "task_skipped", "task_unreachable",
    "handler_start", "handler_ok",
    "migration_start", "migration_step_ok", "migration_step_failed", "migration_end",
    "upgrade_start", "upgrade_step_ok", "upgrade_end",
    "coexistence_provision", "coexistence_cutover", "coexistence_cleanup",
    # ── Track G/seed: agentic security scans (files/vuln-scan/scan-runner.sh) ─
    "scan.batch_started",        # batch picked + dispatching to LLM
    "scan.finding_recorded",     # one finding written to remediation-queue
    "scan.batch_done",           # state file updated, cycle counter checked
    # ── Track G/seed: programmatic security drift (hooks/playbook-end.d/) ────
    "security.drift.snapshot",   # 20-cve-drift-check.sh post-playbook snapshot
    # ── Track E: Tier-2 apps_runner deploy events ──────────────────────────
    "app.deployed",              # one event per onboarded apps/<name>.yml
                                 # manifest after compose up succeeds
    "app.removed",               # operator-triggered tear-down of a Tier-2 app
    # ── A8 conductor + A9.3 remediator agent runs ─────────────────────────
    # agent_run_start / agent_run_end bookend every pulse-run-agent.sh
    # invocation (conductor OR remediator, since A9.3 genericized the
    # runner). conductor_report / remediator_report carry the final
    # markdown body in result_json; Wing's EventRepository whitelist
    # already accepts these (see Wing's PHP VALID_TYPES). Wing-side
    # whitelist and Bone-side whitelist MUST agree — the agent runner
    # POSTs through Bone, so missing entries here turned the live
    # remediator's report-write into a silent 400 (surfaced 2026-05-17
    # during the first non-operator remediator run).
    "agent_run_start", "agent_run_end",
    "conductor_self_test_step", "conductor_report",
    "remediator_report",
    # ── A15 user invitations (operator-issued Authentik invites, 2026-05-17) ─
    # Wing-side UsersPresenter emits both rows directly via EventRepository
    # so they don't traverse Bone in practice; the entries here keep the
    # whitelists aligned so a future Bone POST proxying the same event
    # type (e.g. webhook-driven redemption notification) doesn't 400.
    "user_invitation_issued", "user_invitation_revoked",
    # ── C3 right-to-erasure (tasks/gdpr-forget.yml, 2026-05-25) ─────────────
    # One row per Art. 17 erasure run; Wing-side whitelist must stay aligned.
    # result_json: {subject, dsar_id, services_planned, services_erased, dry_run}.
    "gdpr_forget_user",
    # ── Art-15 right-of-access export (tasks/gdpr-export.yml) ───────────────
    # Forward-ready (no task emits it yet — the gdpr_dsar row is the legal
    # record; mirrors how gdpr_forget_user is whitelist-only). If a future Bone
    # POST proxies a per-run export event, result_json carries: {subject,
    # dsar_id, request_type:'access', services_planned, services_captured,
    # manual_pending, portability_eligible, dry_run, bundle_dir}.
    "gdpr_export_user",
    # ── Consent registry (Art. 6(1)(a) + Art. 7) ──────────────────────────
    # Permit-only, forward-ready (NO live producer yet — record-consent.php
    # writes the gdpr_consent row directly and does NOT emit these; matches the
    # user_invitation_* precedent above, which was whitelisted before a
    # producer existed). Kept aligned with Wing's EventRepository VALID_TYPES so
    # a FUTURE Bone POST proxying a consent event (e.g. a webhook-driven consent
    # capture from an external form) doesn't 400.
    #   consent_granted   — a subject granted consent; result_json would carry
    #                        {consent_id, subject, activity, processing_id,
    #                         tos_version_hash, source}.
    #   consent_withdrawn — a subject withdrew (Art. 7(3)); result_json would
    #                        carry {consent_id?, subject, activity, rows}.
    "consent_granted", "consent_withdrawn",
    # ── Devlog platform (docs/devlog/README.md, 2026-06-12) ────────────────
    # Every WordPress write travels through devlog_lib.emit_bone_event with
    # actor_id=agent:devlog. Wing's EventRepository whitelist must stay
    # aligned (test_devlog_event_types.py).
    #   devlog_entry_created/updated/deleted — tools/devlog-post.py writes to
    #     on-site namespaces; result_json {namespace, slug, wp_post_id, title}.
    #   devlog_sync_run — tasks/devlog-sync.yml bundle reconcile; result_json
    #     {created, updated, deleted, unchanged, bundle_entries, dry_run}.
    #   devlog_published — forward-ready (GH Pages deploy can't reach Bone;
    #     a future operator-side post-release emit would use it).
    "devlog_entry_created", "devlog_entry_updated", "devlog_entry_deleted",
    "devlog_sync_run", "devlog_published",
    # ── Drift backfill (agentic upgrade→migration→coexistence epic, B1) ─────
    # These already live in Wing's EventRepository::VALID_TYPES but were ABSENT
    # from Bone — a pre-existing drift. The migration-author agent emits through
    # AgentKit (agent_session_*…) when run via the runtime, and those traverse
    # Bone; without these here the agent's session events would 400 exactly like
    # the 2026-05-17 remediator_report incident. Backfilled in the SAME commit as
    # the 8 new types below so the twins re-align (test_devlog_event_types.py-style
    # twin-parity gate now pins both halves).
    #   patch_* — apply-patches engine (mirrors upgrade_* / migration_*).
    "patch_start", "patch_step_ok", "patch_step_failed", "patch_end",
    #   AgentKit lifecycle (A14) — every agent session emits start + end;
    #   coordinator sessions also emit thread_*; outcome-driven sessions emit
    #   iteration_*; tool use + grader decisions + outbound/inbound webhooks +
    #   vault resolution complete the family. actor_action_id == agent_sessions.uuid.
    "agent_session_start", "agent_session_end",
    "agent_thread_start", "agent_thread_end",
    "agent_iteration_start", "agent_iteration_end",
    "agent_tool_use", "agent_tool_result",
    "agent_message", "agent_grader_decision",
    "agent_webhook_dispatch", "agent_webhook_receipt",
    "agent_vault_resolved",
    #   Agent approval workflow (A11 — /approvals UI).
    "agent_approval_request", "agent_approval_decision",
    #   Big-red-button platform halt (A12 — /admin emergency control).
    "admin_emergency_halt", "admin_emergency_resume",
    #   E2E journey telemetry (A13 — non-interactive end-to-end testing).
    "e2e_journey_start", "e2e_journey_step", "e2e_journey_end",
    # ── Agentic upgrade→migration→coexistence epic — the 8 NEW types (B1) ───
    # Twin rule (NON-NEGOTIABLE, one commit): every type here MUST also be in
    # Wing's EventRepository::VALID_TYPES or an agent's Bone-proxied POST 400s.
    # See docs/archive/agentic-upgrade-migration-coexistence-design.md §2.6 for
    # the emitter / FK-column / result_json contract of each.
    #   plan_choice_recorded — UpgradesPresenter::actionPlanChoice; uses upgrade_id;
    #     result_json {service, recipe_id, plan_mode, coexistence_planned_id?,
    #     data_copy, port_offset}.
    "plan_choice_recorded",
    #   migration_authored — migration-author agent; uses migration_id (holds uuid);
    #     result_json {service, recipe_id, migration_uuid, artifact_kind,
    #     artifact_path, from_version, to_version}.
    "migration_authored",
    #   migration_pr_opened — migration-author (via migration-pr.sh); uses
    #     migration_id; result_json {migration_uuid, forge, mr_url, forge_branch}.
    "migration_pr_opened",
    #   migration_promoted — operator forge-merge (webhook / --mark-merged); uses
    #     migration_id; result_json {migration_uuid, committed_sha, applied_migration_id?}.
    "migration_promoted",
    #   migration_rejected — operator reject; uses migration_id; result_json
    #     {migration_uuid, rejected_reason}.
    "migration_rejected",
    #   coexistence_promote — toggle-as-primary; uses coexist_svc; result_json
    #     {coexistence_service, from_tag, to_tag, ttl_until}.
    "coexistence_promote",
    #   coexistence_demote — deactivate-secondary / implicit demote; uses
    #     coexist_svc; result_json {coexistence_service, tag, from_role, to_role}.
    "coexistence_demote",
    #   coexistence_cancel — cancel queued; uses coexist_svc; result_json
    #     {coexistence_service, tag, planned_id, reason}.
    "coexistence_cancel",
    # ── A4 (Q3/2026-06-16): manual re-runnable "Copy data" action ───────────
    # The relocated B5 data move (now an explicit verb, not auto-at-cutover).
    # Emitted by Api\CoexistencePresenter::actionCopyData on a COMMITTED copy
    # only (dry_run=false AND Bone 2xx), source='wing', actor_id = the operator
    # (never body-supplied). Twin rule (NON-NEGOTIABLE, one commit): also in
    # Wing's EventRepository::VALID_TYPES, else a Bone-proxied replay 400s.
    # Pinned by tests/anatomy/test_devlog_event_types.py.
    #   coexistence_copy_data — uses coexist_svc; result_json
    #     {coexistence_service, tag, source_migration_id, data_copied_at}.
    "coexistence_copy_data",
    # ── A3 (Q5/2026-06-16): Wing "Promote to migration" Tier-1 button ───────
    # The OPERATOR's supervision event for the button press — distinct from the
    # spawned agent's own agent_session_*/agent_tool_* lineage. Emitted by
    # UpgradesPresenter::emitPromoteRequested with actor_id = the operator
    # (X-Authentik-Username, NEVER the agent), source='wing'. Twin rule
    # (NON-NEGOTIABLE, one commit): also in Wing's EventRepository::VALID_TYPES,
    # else a Bone-proxied replay/forward of this row 400s. Pinned by
    # tests/anatomy/test_devlog_event_types.py.
    #   migration_promote_requested — UpgradesPresenter::actionPromoteToMigration;
    #     actor_id=operator; result_json {service, recipe_id, session_uuid, agent}.
    "migration_promote_requested",
    # ── F3 (2026-06-18): Unqueue / Cancel a planned upgrade (Tier-1) ────────
    # The operator resets a planned upgrade from the /upgrades matrix (the
    # machinery path to re-run the plan-choice flow for a re-test, instead of a
    # hand DB poke). Emitted by UpgradesPresenter::emitUpgradeUnqueued with
    # actor_id = the operator (X-Authentik-Username, NEVER the agent),
    # source='wing'; reuses UpgradeRepository::cancelPlanned (status planned →
    # cancelled). Twin rule (NON-NEGOTIABLE, one commit): also in Wing's
    # EventRepository::VALID_TYPES, else a Bone-proxied replay/forward of this
    # row 400s. Pinned by tests/anatomy/test_devlog_event_types.py.
    #   upgrade_unqueued — UpgradesPresenter::actionCancelPlanned; uses upgrade_id;
    #     result_json {service, recipe_id, target_version, planned_by}.
    "upgrade_unqueued",
}


def verify_hmac(ts_header: str, sig_header: str, raw_body: bytes) -> tuple[bool, str]:
    """Returns (ok, error_reason). Constant-time compare."""
    if not HMAC_SECRET:
        return False, "HMAC secret not configured"
    if not ts_header or not sig_header:
        return False, "missing HMAC headers"
    if not ts_header.isdigit():
        return False, "invalid timestamp"
    drift = abs(int(time.time()) - int(ts_header))
    if drift > 300:
        return False, "timestamp out of window"

    message = f"{ts_header}.{raw_body.decode('utf-8', errors='replace')}"
    expected = hmac.new(
        HMAC_SECRET.encode("utf-8"),
        message.encode("utf-8"),
        digestmod="sha256",
    ).hexdigest()
    # Accept BOTH `<hex>` and `sha256=<hex>` (GitHub-webhook convention used
    # by apps_runner / wing_telemetry). Strip the prefix if present so the
    # constant-time compare works on raw hex either way.
    sig_clean = sig_header[len("sha256="):] if sig_header.startswith("sha256=") else sig_header
    if not hmac.compare_digest(expected, sig_clean):
        return False, "invalid signature"
    return True, ""


def validate_payload(payload: dict[str, Any]) -> str | None:
    for key in ("ts", "type", "run_id"):
        if not payload.get(key):
            return f"missing required field: {key}"
    if payload["type"] not in VALID_TYPES:
        return f"unknown event type: {payload['type']}"
    return None


def insert_event(payload: dict[str, Any]) -> int:
    """Insert into Wing's events table. Returns new row id.

    Thin wrapper over ``clients.wing.insert_event`` — kept here for
    backward-compatibility with existing callers (Bone main.py and
    tests/callback/test_bone_insert_event.py both import
    ``events.insert_event``).
    """
    return _wing.insert_event(payload)
