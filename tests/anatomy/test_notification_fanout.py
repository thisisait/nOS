"""Anatomy gates for the notification fanout system (Anatomy A9, 2026-05-16).

Pins the contracts that A9.1–A9.5 introduced:
  - notifications table schema is declared in schema-extensions.sql
  - NotificationRepository class + DI registration exist
  - Bone notifications module exposes the expected surface
  - Dispatch worker script is present + executable
  - wing-base manifest carries the aggregator spec + routing template
  - gitleaks plugin (first real consumer) declares severity routing
  - Aggregator harvests notification: blocks correctly
  - Routing JSON template renders the expected shape
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest
import yaml

# Anatomy conftest adds files/anatomy/ to sys.path.
from module_utils import load_plugins  # type: ignore  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[2]


# ── Schema + Wing-side surface ──────────────────────────────────────────


def test_notifications_table_declared_in_schema_extensions():
    sql = (REPO / "files/anatomy/wing/db/schema-extensions.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS notifications" in sql
    # Required columns — schema migrations rely on these names.
    for col in (
        "uuid", "severity", "title", "body",
        "actor_id", "actor_action_id", "target_actor_id",
        "origin_plugin", "origin_agent", "source_event_id",
        "channels_json", "wing_inbox_read_at",
        "ntfy_dispatched_at", "ntfy_error",
        "mail_dispatched_at", "mail_error",
        "metadata_json", "created_at",
    ):
        assert col in sql, f"missing column {col} in notifications schema"


def test_notification_repository_class_exists():
    path = REPO / "files/anatomy/wing/app/Model/NotificationRepository.php"
    assert path.is_file()
    src = path.read_text()
    # The repository must expose these methods — Bone + presenter + worker
    # depend on them.
    for name in (
        "function insert",
        "function query",
        "function findByUuid",
        "function countUnread",
        "function markRead",
        "function pendingForChannel",
        "function markDispatched",
    ):
        assert name in src, f"NotificationRepository missing {name}"
    # Severity + channel whitelists pinned in code.
    assert "'critical'" in src and "'high'" in src and "'medium'" in src
    assert "'wing-inbox'" in src and "'ntfy'" in src and "'mail'" in src


def test_notification_repository_registered_in_di():
    neon = (REPO / "files/anatomy/wing/app/config/common.neon").read_text()
    assert "App\\Model\\NotificationRepository" in neon


def test_inbox_presenter_uses_notification_repository():
    src = (REPO / "files/anatomy/wing/app/Presenters/InboxPresenter.php").read_text()
    assert "NotificationRepository" in src
    assert "actionMarkRead" in src
    # POST-only gate on the mutating action — anatomy invariant.
    assert "requirePostMethod" in src


# ── Bone-side surface ───────────────────────────────────────────────────


def test_bone_notifications_module_exists():
    path = REPO / "files/anatomy/bone/notifications.py"
    assert path.is_file()
    src = path.read_text()
    for name in ("VALID_SEVERITIES", "VALID_CHANNELS",
                 "validate_payload", "insert_notification",
                 "verify_hmac"):
        assert name in src, f"bone/notifications.py missing {name}"


def test_bone_wing_client_extended():
    """clients/wing.py must carry the notification helpers used by the
    Bone POST handler + the channel-routing fallback (A9.5).
    """
    src = (REPO / "files/anatomy/bone/clients/wing.py").read_text()
    for name in ("def insert_notification",
                 "def query_notifications",
                 "def _load_routing",
                 "def _lookup_channels",
                 "_VALID_SEVERITIES",
                 "_VALID_CHANNELS"):
        assert name in src, f"clients/wing.py missing {name}"


def test_bone_main_registers_notifications_route():
    src = (REPO / "files/anatomy/bone/main.py").read_text()
    assert '"/api/v1/notifications"' in src
    assert "notifications_ingest" in src
    assert "notifications_list" in src


# ── Dispatch worker ─────────────────────────────────────────────────────


def test_dispatch_worker_script_present():
    path = REPO / "files/anatomy/wing/bin/dispatch-notifications.php"
    assert path.is_file()
    src = path.read_text()
    # Both channels handled.
    assert "deliver_ntfy" in src
    assert "deliver_mail" in src
    # Idempotency lock via the dispatched_at column.
    assert "mark_dispatched" in src
    assert "ntfy_dispatched_at" in src
    assert "mail_dispatched_at" in src


def test_wing_base_registers_dispatch_pulse_job():
    manifest = yaml.safe_load(
        (REPO / "files/anatomy/plugins/wing-base/plugin.yml").read_text()
    )
    jobs = (manifest.get("pulse") or {}).get("jobs") or []
    names = [j.get("name") for j in jobs]
    assert "dispatch-notifications" in names, names
    job = next(j for j in jobs if j["name"] == "dispatch-notifications")
    assert job["runner"] == "subprocess"
    # Per-minute cadence — empty queue is cheap, partial failures retry fast.
    assert job["schedule"] == "* * * * *"
    # A9 daily-digest knob exposed via env.
    assert "DISPATCH_MAIL_DIGEST_FLOOR" in job.get("env", {})


def test_wing_base_registers_digest_flush_pulse_job():
    """A9 daily-digest companion (2026-05-17): a daily Pulse job calls the
    same dispatch script with DISPATCH_DIGEST_FLUSH=1 to batch queued rows
    into one summary email.
    """
    manifest = yaml.safe_load(
        (REPO / "files/anatomy/plugins/wing-base/plugin.yml").read_text()
    )
    jobs = (manifest.get("pulse") or {}).get("jobs") or []
    names = [j.get("name") for j in jobs]
    assert "dispatch-notifications-digest" in names, names
    job = next(j for j in jobs if j["name"] == "dispatch-notifications-digest")
    assert job["runner"] == "subprocess"
    env = job.get("env") or {}
    assert env.get("DISPATCH_DIGEST_FLUSH") == "1"
    # Schedule defaults to 09:00 UTC daily but accepts operator override.
    assert "mail_digest_cron" in job["schedule"] or job["schedule"] == "0 9 * * *"


def test_notifications_schema_carries_mail_digest_window():
    """A9 daily-digest schema (2026-05-17): per-row queue marker column +
    partial index for cheap pending-flush queries.
    """
    sql = (REPO / "files/anatomy/wing/db/schema-extensions.sql").read_text()
    assert "mail_digest_window" in sql
    assert "idx_notifications_mail_digest" in sql


def test_init_db_alters_in_mail_digest_window():
    """Existing wing.db installs from pre-2026-05-17 cutover get the
    column added by init-db.php's idempotent ALTER sweep.
    """
    src = (REPO / "files/anatomy/wing/bin/init-db.php").read_text()
    assert "$addMissingColumns($db, 'notifications'" in src
    assert "'mail_digest_window' => 'TEXT'" in src


def test_dispatch_worker_handles_digest_path():
    """Dispatch worker has the three new code paths: digest-floor queue
    decision, fetch_digest_queue helper, deliver_mail_digest aggregator.
    """
    src = (REPO / "files/anatomy/wing/bin/dispatch-notifications.php").read_text()
    assert "DISPATCH_MAIL_DIGEST_FLOOR" in src
    assert "DISPATCH_DIGEST_FLUSH" in src
    assert "queue_for_digest" in src
    assert "fetch_digest_queue" in src
    assert "deliver_mail_digest" in src
    # The per-minute mail SELECT must exclude already-queued rows.
    assert "mail_digest_window IS NULL" in src


def test_default_config_exposes_digest_knobs():
    cfg = (REPO / "default.config.yml").read_text()
    assert "mail_digest_floor:" in cfg
    assert "mail_digest_cron:" in cfg


# ── Aggregator wiring (A9.5) ───────────────────────────────────────────


def test_wing_base_declares_notification_aggregator():
    manifest = yaml.safe_load(
        (REPO / "files/anatomy/plugins/wing-base/plugin.yml").read_text()
    )
    aggs = manifest.get("aggregates") or []
    spec_paths = [(a.get("from"), a.get("block_path")) for a in aggs]
    assert ("consumer_block", "notification") in spec_paths
    assert ("agent_profile", "notification") in spec_paths
    # Render target sidecar declared.
    prov = (manifest.get("provisioning") or {}).get("notification_routing") or {}
    assert prov.get("template") == "templates/notification-routing.json.j2"
    assert "notification-routing.json" in (prov.get("target") or "")


def test_routing_template_exists():
    path = REPO / "files/anatomy/plugins/wing-base/templates/notification-routing.json.j2"
    assert path.is_file()
    src = path.read_text()
    # Iterates the aggregated input variable.
    assert "inputs.notification_routing" in src
    # Renders the canonical severity keys.
    for sev in ("on_critical", "on_high", "on_medium", "on_low", "on_info"):
        assert sev in src


def test_gitleaks_declares_notification_routing():
    """The first real consumer pins the routing-block contract."""
    manifest = yaml.safe_load(
        (REPO / "files/anatomy/plugins/gitleaks/plugin.yml").read_text()
    )
    notif = manifest.get("notification") or {}
    assert notif.get("on_critical") == ["wing-inbox", "ntfy", "mail"]
    assert notif.get("on_high") == ["wing-inbox", "ntfy"]
    assert notif.get("on_medium") == ["wing-inbox"]
    # on_low / on_info explicitly empty (silent log floor).
    assert notif.get("on_low") == []
    assert notif.get("on_info") == []


def test_gitleaks_skill_emits_notification():
    """First live consumer: gitleaks skill POSTs a notification after
    a successful ingest with INSERTED > 0. Pin the contract so a future
    refactor can't silently drop the emit.
    """
    script = (REPO / "files/anatomy/plugins/gitleaks/skills/run-gitleaks.sh").read_text()
    # Conditional emit gate present.
    assert 'WING_EVENTS_HMAC_SECRET' in script
    assert '"$INSERTED" -gt 0' in script
    # Posts to the right endpoint with HMAC.
    assert '/api/v1/notifications' in script
    assert 'X-Wing-Timestamp' in script
    assert 'X-Wing-Signature' in script
    # Origin attribution stays consistent with the routing-block plugin name.
    assert 'origin_plugin: "gitleaks"' in script or 'origin_plugin": "gitleaks"' in script
    # And the plugin manifest exports the HMAC secret + bone URL to the env.
    manifest = yaml.safe_load(
        (REPO / "files/anatomy/plugins/gitleaks/plugin.yml").read_text()
    )
    job = next(j for j in (manifest.get("pulse") or {}).get("jobs", [])
               if j.get("name") == "nightly-scan")
    env = job.get("env") or {}
    assert "WING_EVENTS_HMAC_SECRET" in env
    assert "BONE_API_URL" in env


def test_conductor_profile_declares_notification_routing():
    """Second live consumer (agent path): conductor agent profile pins
    its severity routing so pulse-run-agent.sh failures escalate."""
    profile = yaml.safe_load(
        (REPO / "files/anatomy/agents/conductor.yml").read_text()
    )
    notif = profile.get("notification") or {}
    assert notif.get("on_critical") == ["wing-inbox", "ntfy", "mail"]
    assert notif.get("on_high") == ["wing-inbox", "ntfy"]
    assert notif.get("on_medium") == ["wing-inbox"]


def test_pulse_run_agent_emits_notification_on_failure():
    """The pulse-run-agent.sh runner posts a notification when CLAUDE_EXIT != 0.
    Mirrors the gitleaks contract — Bone HMAC + origin_agent + severity
    mapped to exit-code class. Post-A9.3 the runner is generic across
    agents, so origin_agent is the dynamic $AGENT_NAME rather than a
    hardcoded "conductor".
    """
    script = (REPO / "files/anatomy/scripts/pulse-run-agent.sh").read_text()
    assert "_post_wing_notification" in script
    assert "/api/v1/notifications" in script
    # A9.3: origin_agent is dynamic ($AGENT_NAME variable), no longer
    # hardcoded. The HMAC body builds it via jq from --arg agent.
    assert "origin_agent: $agent" in script
    assert 'AGENT_NAME' in script
    # Exit-class → severity map.
    assert 'NOTIF_SEV="critical"' in script
    assert 'NOTIF_SEV="high"' in script
    assert '"$CLAUDE_EXIT" -ne 0' in script


def test_aggregator_agent_profile_sets_slug(tmp_path):
    """A9.5 fix: agent_profile branch of the aggregator must stamp slug
    + plugin_name so the rendered routing JSON has a stable key Bone can
    look up via origin_agent.
    """
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "plugin.yml").write_text(yaml.safe_dump({
        "name": "src", "version": "0.1.0", "type": ["service"],
        "aggregates": [{"from": "agent_profile",
                        "block_path": "notification",
                        "output_var": "agents"}],
        "gdpr": {"data_categories": ["test"], "data_subjects": ["operator"],
                 "legal_basis": "legitimate_interests", "retention_days": 365,
                 "processors": []},
    }))
    plugins = load_plugins.discover(tmp_path)
    profiles = [{"name": "conductor",
                 "notification": {"on_critical": ["mail"], "on_high": []}}]
    load_plugins.run_aggregators(plugins, agent_profiles=profiles)
    routed = plugins[0].inputs.get("agents") or []
    assert len(routed) == 1
    assert routed[0]["slug"] == "conductor"
    assert routed[0]["plugin_name"] == "conductor"


def test_aggregator_harvests_notification_blocks(tmp_path):
    """End-to-end aggregator smoke — wing-base picks up peer blocks."""
    (tmp_path / "wing-base").mkdir()
    (tmp_path / "wing-base" / "plugin.yml").write_text(yaml.safe_dump({
        "name": "wing-base",
        "version": "0.1.0",
        "type": ["service"],
        "aggregates": [{
            "from": "consumer_block",
            "block_path": "notification",
            "output_var": "notification_routing",
        }],
        "gdpr": {"data_categories": ["test"], "data_subjects": ["operator"],
                 "legal_basis": "legitimate_interests", "retention_days": 365,
                 "processors": []},
    }))
    (tmp_path / "gitleaks").mkdir()
    (tmp_path / "gitleaks" / "plugin.yml").write_text(yaml.safe_dump({
        "name": "gitleaks",
        "version": "0.1.0",
        "type": ["skill"],
        "notification": {
            "on_critical": ["wing-inbox", "ntfy", "mail"],
            "on_high": ["wing-inbox", "ntfy"],
            "on_medium": ["wing-inbox"],
            "on_low": [],
            "on_info": [],
        },
        "gdpr": {"data_categories": ["test"], "data_subjects": ["operator"],
                 "legal_basis": "legitimate_interests", "retention_days": 365,
                 "processors": []},
    }))
    plugins = load_plugins.discover(tmp_path)
    load_plugins.run_aggregators(plugins)
    wing = next(p for p in plugins if p.name == "wing-base")
    routing = wing.inputs.get("notification_routing") or []
    assert len(routing) == 1
    assert routing[0]["plugin_name"] == "gitleaks"
    assert routing[0]["on_critical"] == ["wing-inbox", "ntfy", "mail"]
