-- AUTO-GENERATED — do not edit by hand.
-- Source: files/anatomy/wing/bin/init-db.php +
--         files/anatomy/wing/db/schema-extensions.sql +
--         files/anatomy/wing/db/gdpr-seed.sql
-- Regenerate: php files/anatomy/wing/bin/export-schema.php
-- CI drift check: .github/workflows/ci.yml — contracts-drift job.

PRAGMA foreign_keys = ON;

-- ============================================================
-- TABLES (41)
-- ============================================================

CREATE TABLE advisories (
		id          INTEGER PRIMARY KEY AUTOINCREMENT,
		filename    TEXT NOT NULL UNIQUE,
		title       TEXT,
		date        TEXT NOT NULL,
		has_critical INTEGER NOT NULL DEFAULT 0,
		has_pentest INTEGER NOT NULL DEFAULT 0,
		full_text   TEXT NOT NULL,
		scan_cycle  INTEGER,
		created_at  TEXT NOT NULL DEFAULT (datetime('now'))
	);

CREATE TABLE agent_credentials (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    vault_id        INTEGER NOT NULL,
    scope           TEXT NOT NULL,                    -- anthropic-api | mcp-wing | mcp-bone | infisical | …
    display_name    TEXT NOT NULL,
    secret_ref      TEXT NOT NULL,                    -- "env:ANTHROPIC_API_KEY" or "infisical:/wing/anthropic-api"
    expires_at      TEXT,
    archived_at     TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (vault_id) REFERENCES agent_vaults(id)
);

CREATE TABLE agent_iterations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_uuid    TEXT NOT NULL,
    iteration       INTEGER NOT NULL,                 -- 0-indexed
    grader_result   TEXT NOT NULL,                    -- satisfied | needs_revision | failed
    grader_feedback TEXT,                             -- markdown bullets
    grader_model    TEXT NOT NULL,
    duration_ms     INTEGER,
    tokens_input    INTEGER,
    tokens_output   INTEGER,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE agent_memory_stores (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid                TEXT NOT NULL UNIQUE,
    agent_name          TEXT NOT NULL,
    title               TEXT NOT NULL,
    content             TEXT NOT NULL,            -- markdown / text body
    source_session_uuid TEXT,                     -- session that produced/updated this entry
    trace_id            TEXT,                     -- W3C trace_id for cross-link
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE agent_sessions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid            TEXT NOT NULL UNIQUE,             -- A10 actor_action_id
    agent_name      TEXT NOT NULL,                    -- matches files/anatomy/agents/<name>/
    agent_version   INTEGER NOT NULL,                 -- pinned at session start
    status          TEXT NOT NULL,                    -- pending | running | idle | terminated
    trigger         TEXT NOT NULL,                    -- pulse | webhook | operator
    trigger_id      TEXT,                             -- pulse_run_id or webhook event uuid
    actor_id        TEXT NOT NULL,                    -- 'agent:<name>' for self, else operator
    trace_id        TEXT NOT NULL,                    -- W3C Trace Context (32 hex chars)
    model_uri       TEXT NOT NULL,                    -- e.g. anthropic-claude-opus-4-7
    outcome_id      TEXT,                             -- present iff outcome-driven session
    outcome_result  TEXT,                             -- satisfied | needs_revision | max_iterations_reached | failed | interrupted
    started_at      TEXT NOT NULL,
    ended_at        TEXT,
    stop_reason     TEXT,                             -- end_turn | max_tokens | tool_use | error | interrupted
    tokens_input    INTEGER,
    tokens_output   INTEGER,
    tokens_cache_read INTEGER,
    result_json     TEXT,                             -- terminal payload + summary
    error_json      TEXT,                             -- present iff status=terminated with error
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE agent_subscriptions (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid                    TEXT NOT NULL UNIQUE,
    url                     TEXT NOT NULL,            -- HTTPS only at runtime gate
    event_types             TEXT NOT NULL,            -- comma-separated whitelist
    signing_secret          TEXT NOT NULL,            -- whsec_... 32 random bytes hex
    enabled                 INTEGER NOT NULL DEFAULT 1,
    consecutive_failures    INTEGER NOT NULL DEFAULT 0,
    last_attempted_at       TEXT,
    last_succeeded_at       TEXT,
    disabled_reason         TEXT,
    created_at              TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at              TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE agent_threads (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid                TEXT NOT NULL UNIQUE,
    session_uuid        TEXT NOT NULL,
    parent_thread_uuid  TEXT,                         -- null for primary
    agent_name          TEXT NOT NULL,
    agent_version       INTEGER NOT NULL,
    role                TEXT NOT NULL,                -- primary | child
    status              TEXT NOT NULL,                -- pending | running | idle | terminated
    trace_id            TEXT NOT NULL,
    span_id             TEXT NOT NULL,                -- 16 hex chars, parent for all LLM-call spans
    started_at          TEXT NOT NULL,
    ended_at            TEXT,
    stop_reason         TEXT,
    tokens_input        INTEGER,
    tokens_output       INTEGER,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE agent_vaults (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid            TEXT NOT NULL UNIQUE,
    name            TEXT NOT NULL UNIQUE,             -- e.g. "conductor-default", "code-reviewer-org-acme"
    display_name    TEXT NOT NULL,
    metadata_json   TEXT NOT NULL DEFAULT '{}',
    archived_at     TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE api_tokens (
		id          INTEGER PRIMARY KEY AUTOINCREMENT,
		token       TEXT NOT NULL UNIQUE,
		name        TEXT NOT NULL DEFAULT 'default',
		created_by  TEXT,
		created_at  TEXT NOT NULL DEFAULT (datetime('now')),
		last_used_at TEXT,
		active      INTEGER NOT NULL DEFAULT 1
	);

CREATE TABLE attack_probes (
		id          INTEGER PRIMARY KEY AUTOINCREMENT,
		cycle_mod   INTEGER NOT NULL,
		name        TEXT NOT NULL UNIQUE,
		description TEXT,
		last_run    TEXT,
		findings    INTEGER NOT NULL DEFAULT 0,
		completed   INTEGER NOT NULL DEFAULT 0
	);

CREATE TABLE audit_chain_meta (
    k  TEXT PRIMARY KEY,
    v  TEXT
);

CREATE TABLE coexistence_planned (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    service       TEXT NOT NULL,
    tag           TEXT NOT NULL DEFAULT 'new',
    target_version TEXT,
    port_offset   INTEGER DEFAULT 10,
    reason        TEXT,
    planned_by    TEXT NOT NULL DEFAULT 'operator',
    status        TEXT NOT NULL DEFAULT 'planned',   -- planned | applied | cancelled
    planned_at    TEXT NOT NULL DEFAULT (datetime('now')),
    applied_at    TEXT, parent_upgrade_id INTEGER, source_migration_uuid TEXT, data_copy INTEGER NOT NULL DEFAULT 1, cancelled_at TEXT, cancelled_by TEXT,
    UNIQUE (service, tag, status)
);

CREATE TABLE coexistence_tracks (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    service       TEXT NOT NULL,
    tag           TEXT NOT NULL,
    version       TEXT,
    port          INTEGER,
    data_path     TEXT,
    active        INTEGER NOT NULL DEFAULT 0,
    read_only     INTEGER NOT NULL DEFAULT 0,
    started_at    TEXT,
    cutover_at    TEXT,
    ttl_until     TEXT,
    updated_at    TEXT NOT NULL DEFAULT (datetime('now')), role TEXT NOT NULL DEFAULT 'secondary', lifecycle TEXT NOT NULL DEFAULT 'provisioned', source_migration_id TEXT, promoted_at TEXT, deactivated_at TEXT,
    UNIQUE(service, tag)
);

CREATE TABLE component_scan_state (
		component_id        TEXT NOT NULL PRIMARY KEY REFERENCES systems(id) ON DELETE CASCADE,
		last_checked        TEXT,
		last_cve_scan       TEXT,
		last_misconfig_scan TEXT,
		last_attack_probe   TEXT,
		findings_count      INTEGER NOT NULL DEFAULT 0,
		status              TEXT NOT NULL DEFAULT 'pending'
	);

CREATE TABLE events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            TEXT NOT NULL,           -- ISO-8601
    run_id        TEXT NOT NULL,
    type          TEXT NOT NULL,
    playbook      TEXT,
    play          TEXT,
    task          TEXT,
    role          TEXT,
    host          TEXT,
    duration_ms   INTEGER,
    changed       INTEGER,                 -- 0/1
    result_json   TEXT,                    -- JSON blob
    migration_id  TEXT,
    upgrade_id    TEXT,
    patch_id      TEXT,
    coexist_svc   TEXT,
    -- source: who wrote this event. Anatomy P1 (2026-05-05) closes the
    -- pre-A8 attribution gap noted in CLAUDE.md "Wing /events table
    -- schema mismatch" tech debt. Bone's POST handler accepted `source`
    -- in JSON but silently dropped it on insert; analysts had to guess
    -- attribution from `task` text prefixes. Common values:
    --   "callback" — Ansible callback plugin (default for playbook runs)
    --   "operator" — manual curl/API hit
    --   "agent:<name>" — A8 conductor + future agent runs (with run id)
    -- Pre-A10 `source` was hint-level free text; A10 (2026-05-08) adds
    -- `actor_id` (Authentik client_id of the writer) + `actor_action_id`
    -- (UUID per logical action — same UUID across multiple events that
    -- belong to one logical operation, e.g. agent_run_start + run_end).
    -- `source` stays as a coarse channel label; `actor_id` is the
    -- cryptographic identity. Pulse runs that span multiple events
    -- emit a stable actor_action_id from pulse-run-agent.sh.
    source        TEXT,
    actor_id          TEXT,                  -- Authentik client_id (operator/agent/plugin)
    actor_action_id   TEXT,                  -- UUID grouping events of one logical action
    acted_at          TEXT,                  -- ISO-8601; usually = ts, kept separate for backfilled rows
    prev_hash     TEXT,                    -- HMAC chain: previous chained row's row_hash (NULL = unsigned legacy/chain-off row)
    row_hash      TEXT,                    -- HMAC chain: HMAC(chainKey, prev_hash || canonical(immutable fields)); see app/Model/AuditChain.php
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE gdpr_breaches (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    detected_at         TEXT NOT NULL,
    notified_supervisor_at TEXT,                    -- 72h deadline tracker
    notified_subjects_at   TEXT,                    -- when "high risk"
    nature              TEXT NOT NULL,              -- short headline
    affected_subjects   INTEGER,
    likely_consequences TEXT,
    measures_taken      TEXT,
    status              TEXT NOT NULL,              -- detected | notified | resolved | non-reportable
    -- Breach-notification engine (gov P1, 2026-05-31): GDPR Art-33/34 + NIS2/ZKB
    -- (NÚKIB) deadline columns. *_due_at are stamped once at file-time by
    -- App\Model\BreachDeadlines; NULL = stage not applicable (risk/scope gate).
    aware_at                   TEXT,                -- ISO-8601 UTC; Art-33 72h anchor ('became aware'); defaults to detected_at
    risk_level                 TEXT NOT NULL DEFAULT 'none',  -- none|low|medium|high (Art-33 gate: !=none; Art-34 gate: ==high)
    data_categories            TEXT,                -- Art-33(3)(a)
    affected_records           INTEGER,             -- Art-33(3)(a) approx record count
    art33_due_at               TEXT,                -- aware_at + 72h (NULL when not reportable)
    art34_due_at               TEXT,                -- report-only marker; never escalated by the scan
    art34_exception            TEXT,                -- NULL | encryption | risk_mitigated | disproportionate_effort (Art-34(3))
    nis2_in_scope              INTEGER NOT NULL DEFAULT 0,    -- 0/1; cyber-incident owes NÚKIB notifications
    nis2_regime                TEXT,                -- higher | lower | critical_infra
    nis2_cross_border          INTEGER NOT NULL DEFAULT 0,
    nis2_intentional_suspected INTEGER NOT NULL DEFAULT 0,
    nis2_early_warning_due_at  TEXT,                -- detected_at + 24h
    nis2_early_warning_done_at TEXT,
    nis2_notification_due_at   TEXT,                -- detected_at + 72h (NÚKIB, distinct from GDPR 72h)
    nis2_notification_done_at  TEXT,
    nis2_final_report_due_at   TEXT,                -- detected_at + 1 month (end-of-month clamped)
    nis2_final_report_done_at  TEXT,
    regulator_ref              TEXT,                -- UOOU/NÚKIB case id returned after filing
    escalated_stages_json      TEXT NOT NULL DEFAULT '[]',  -- de-dup stamp of stages already alerted
    notes               TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE gdpr_consent (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_email       TEXT NOT NULL,                    -- the data subject
    processing_id       TEXT,                             -- soft FK gdpr_processing.id; NULL = cross-cutting
    activity            TEXT NOT NULL,                    -- consented-to activity slug (e.g. "marketing-email")
    lawful_basis        TEXT NOT NULL DEFAULT 'consent',  -- Art. 6(1) basis; normally 'consent'
    tos_version_hash    TEXT,                             -- hash of the terms presented (NOT a secret, NOT proof of valid consent)
    source              TEXT NOT NULL DEFAULT 'operator', -- operator | ui | api | import — how consent arrived
    granted_at          TEXT NOT NULL,                    -- ISO-8601; when consent was given
    withdrawn_at        TEXT,                             -- ISO-8601; NULL = still active (Art. 7(3))
    notes               TEXT,                             -- free-form (e.g. UI request id, operator note)
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE gdpr_dsar (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    received_at         TEXT NOT NULL,
    subject_email       TEXT NOT NULL,
    request_type        TEXT NOT NULL,              -- access | rectify | erase | portability | object
    status              TEXT NOT NULL,              -- received | in-progress | completed | rejected
    completed_at        TEXT,
    rejection_reason    TEXT,
    processing_ids      TEXT NOT NULL DEFAULT '[]', -- JSON array of gdpr_processing.id touched
    notes               TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE gdpr_processing (
    id                  TEXT PRIMARY KEY,           -- stable slug (auth, telemetry, …)
    name                TEXT NOT NULL,              -- human-readable
    purpose             TEXT NOT NULL,              -- why we process this data
    legal_basis         TEXT NOT NULL,              -- contract | consent | legitimate-interest | …
    data_categories     TEXT NOT NULL,              -- JSON array of names
    data_subjects       TEXT NOT NULL,              -- JSON array (operators, end-users, …)
    retention_days      INTEGER,                    -- NULL = indefinite (justify in notes)
    storage_location    TEXT NOT NULL,              -- where the data physically lives
    transfers_outside_eu INTEGER NOT NULL DEFAULT 0, -- 0/1
    processors          TEXT NOT NULL DEFAULT '[]', -- JSON array of third-party processors
    security_measures   TEXT NOT NULL DEFAULT '[]', -- JSON array of mitigations
    notes               TEXT,                       -- free-form
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE gitleaks_findings (
    id            TEXT PRIMARY KEY,             -- UUID4 generated Wing-side
    fingerprint   TEXT NOT NULL,                -- gitleaks key: commit_sha:file:line:rule_id
    rule_id       TEXT NOT NULL,                -- e.g. "generic-api-key", "aws-access-token"
    description   TEXT,                         -- human-readable from gitleaks rule
    secret_masked TEXT,                         -- first 4 + "…" + last 4 (never full secret)
    file_path     TEXT NOT NULL,
    line_start    INTEGER NOT NULL,
    commit_sha    TEXT,                         -- git SHA of introducing commit
    author        TEXT,                         -- git author name/email
    date          TEXT,                         -- ISO-8601 commit date
    severity      TEXT NOT NULL DEFAULT 'high', -- critical|high|medium|low|info
    repo_path     TEXT NOT NULL,                -- absolute path to scanned repo
    scan_id       TEXT,                         -- soft FK → pulse_runs.run_id; NULL = ad-hoc
    resolved_at   TEXT,                         -- NULL = open; set by operator action
    resolved_by   TEXT,                         -- Authentik client_id or free-text note
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE migrations_applied (
    id                TEXT PRIMARY KEY,
    title             TEXT NOT NULL,
    severity          TEXT NOT NULL,
    applied_at        TEXT NOT NULL,
    success           INTEGER NOT NULL,    -- 0/1
    duration_sec      INTEGER,
    steps_applied     INTEGER,
    steps_total       INTEGER,
    rolled_back_from  TEXT,
    event_run_id      TEXT,
    raw_record_json   TEXT                  -- full migration record
);

CREATE TABLE migrations_authored (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid            TEXT NOT NULL UNIQUE,            -- UUID4 == authoring agent_sessions.uuid / actor_action_id
    service         TEXT NOT NULL,                  -- soft FK upgrade_recipes.service
    recipe_id       TEXT NOT NULL,                  -- soft FK upgrade_recipes.recipe_id (the promoted recipe)
    migration_id    TEXT,                           -- files/anatomy/migrations/<ISO>-<slug>.yml id (== filename)
    plan_mode       TEXT NOT NULL DEFAULT 'migration', -- migration | coexist (carried from the plan-choice)
    from_version    TEXT,
    to_version      TEXT,
    severity        TEXT,                           -- patch | minor | breaking | security (mirrors recipe)
    title           TEXT NOT NULL,
    artifact_kind   TEXT NOT NULL DEFAULT 'migration_yaml', -- migration_yaml | recipe_apply_body | role_task
    artifact_path   TEXT,                           -- repo-relative path the MR touches
    forge           TEXT,                           -- gitlab | gitea
    mr_url          TEXT,                           -- LOCAL forge MR/PR URL (NEVER GitHub)
    forge_branch    TEXT,                           -- fix/migration-<svc>-<ts>
    committed_sha   TEXT,                           -- set once review_status=merged
    review_status   TEXT NOT NULL DEFAULT 'draft',  -- draft | in_review | merged | rejected | superseded
    rejected_reason TEXT,
    author_agent    TEXT NOT NULL DEFAULT 'migration-author', -- == actor_id minus "agent:"
    session_uuid    TEXT,                           -- soft FK agent_sessions.uuid (lineage deep-link)
    actor_id        TEXT,                           -- agent:migration-author (or operator on manual promote)
    actor_action_id TEXT,                           -- == session_uuid
    applied_migration_id TEXT,                       -- soft FK migrations_applied.id once it RUNS
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (service, recipe_id, review_status)       -- one live draft/in_review per (svc,recipe); delete-prior to flip
);

CREATE TABLE notifications (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid                TEXT NOT NULL UNIQUE,           -- UUID4 minted at insert
    severity            TEXT NOT NULL,                  -- critical|high|medium|low|info
    title               TEXT NOT NULL,                  -- one-line subject (shown in inbox list)
    body                TEXT,                           -- markdown / plain text detail
    actor_id            TEXT,                           -- A10: who emitted (operator / agent:<name> / plugin:<slug>)
    actor_action_id     TEXT,                           -- A10: groups with source event
    target_actor_id     TEXT NOT NULL DEFAULT 'operator', -- whom to notify (Authentik client_id or 'operator')
    origin_plugin       TEXT,                           -- plugin slug if plugin-emitted
    origin_agent        TEXT,                           -- agent name if agent-emitted
    source_event_id     INTEGER,                        -- soft FK events.id for audit deep-link
    channels_json       TEXT NOT NULL DEFAULT '["wing-inbox"]',  -- JSON array: subset of [wing-inbox, ntfy, mail]
    wing_inbox_read_at  TEXT,                           -- NULL = unread; mark-read action sets this
    ntfy_dispatched_at  TEXT,                           -- NULL = pending (only meaningful if "ntfy" in channels)
    ntfy_error          TEXT,
    mail_dispatched_at  TEXT,
    mail_error          TEXT,
    -- A9 daily-digest mail (2026-05-17): when the per-minute worker decides
    -- a row belongs in the digest queue (severity ≤ DISPATCH_MAIL_DIGEST_FLOOR
    -- AND `mail` ∈ channels), it stamps this column with the queue-entry time
    -- and leaves mail_dispatched_at NULL. The daily digest worker batches
    -- every row where mail_digest_window IS NOT NULL AND mail_dispatched_at
    -- IS NULL into ONE summary email and sets mail_dispatched_at for the
    -- whole batch at once. Immediate-dispatch rows (severity > floor) leave
    -- this NULL and get stamped directly.
    mail_digest_window  TEXT,
    metadata_json       TEXT NOT NULL DEFAULT '{}',     -- per-channel hints (ntfy click URL, mail recipients override, ...)
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE patches (
		id              TEXT PRIMARY KEY,
		finding_ref     TEXT,
		component_id    TEXT,
		upstream_repo   TEXT,
		description     TEXT,
		patch_file      TEXT,
		tests_added     TEXT,
		upstream_pr     TEXT,
		status          TEXT NOT NULL DEFAULT 'draft',
		created_at      TEXT NOT NULL DEFAULT (datetime('now')),
		updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
	);

CREATE TABLE patches_applied (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    patch_id          TEXT NOT NULL,           -- PATCH-NNN (FK to patches.id)
    component_id      TEXT,
    finding_ref       TEXT,
    applied_at        TEXT NOT NULL,
    success           INTEGER NOT NULL,
    duration_sec      INTEGER,
    rolled_back       INTEGER NOT NULL DEFAULT 0,
    event_run_id      TEXT,
    raw_record_json   TEXT
);

CREATE TABLE pentest_areas_planned (
		id                  INTEGER PRIMARY KEY AUTOINCREMENT,
		target_id           TEXT NOT NULL REFERENCES pentest_targets(id) ON DELETE CASCADE,
		area                TEXT NOT NULL,
		description         TEXT,
		files_of_interest   TEXT,
		methods_of_interest TEXT,
		attack_class        TEXT,
		priority            TEXT DEFAULT 'medium',
		rationale           TEXT,
		created_at          TEXT NOT NULL DEFAULT (datetime('now'))
	);

CREATE TABLE pentest_areas_tested (
		id              INTEGER PRIMARY KEY AUTOINCREMENT,
		target_id       TEXT NOT NULL REFERENCES pentest_targets(id) ON DELETE CASCADE,
		area            TEXT NOT NULL,
		date            TEXT NOT NULL DEFAULT (datetime('now')),
		technique       TEXT,
		files_reviewed  TEXT,
		result          TEXT NOT NULL CHECK (result IN ('no_findings','potential_vuln','confirmed_vuln')),
		details         TEXT,
		next_steps      TEXT,
		created_at      TEXT NOT NULL DEFAULT (datetime('now'))
	);

CREATE TABLE pentest_findings (
		id                      TEXT PRIMARY KEY,
		target_id               TEXT NOT NULL REFERENCES pentest_targets(id) ON DELETE CASCADE,
		severity                TEXT NOT NULL CHECK (severity IN ('CRITICAL','HIGH','MEDIUM','LOW')),
		title                   TEXT NOT NULL,
		description             TEXT,
		affected_versions       TEXT,
		proof_of_concept        TEXT,
		files                   TEXT,
		attack_class            TEXT,
		exploitability          TEXT,
		confidence              TEXT DEFAULT 'medium',
		disclosure_status       TEXT DEFAULT 'not_reported',
		upstream_issue          TEXT,
		patch_pr                TEXT,
		-- A10 direct attribution (2026-05-17, A9.4): who discovered + who resolved.
		-- Pre-this only indirect via target_id → pentest_targets (which itself
		-- didn't carry attribution). Inspektor's runner (deferred) will write
		-- discovered_by='agent:inspektor'; operator + remediator close
		-- findings via /api/v1/pentest/findings/<id>/resolve with the bearer-
		-- token-derived actor_id (same canonical pattern as
		-- GitleaksPresenter::actionResolve post-2026-05-17 security fix).
		discovered_by           TEXT,
		resolved_at             TEXT,
		resolved_by             TEXT,
		nos_mitigation    TEXT,
		remediation             TEXT,
		found_at                TEXT NOT NULL DEFAULT (datetime('now')),
		created_at              TEXT NOT NULL DEFAULT (datetime('now'))
	);

CREATE TABLE pentest_targets (
		id              TEXT PRIMARY KEY,
		component_id    TEXT NOT NULL,
		version_tested  TEXT,
		upstream_repo   TEXT,
		language        TEXT,
		attack_surface  TEXT,
		status          TEXT NOT NULL DEFAULT 'planned',
		-- A10 attribution (2026-05-17). Operator or inspektor agent. Filled
		-- via getActorId() in the PentestPresenter create + update paths;
		-- old rows stay NULL.
		created_by      TEXT,
		created_at      TEXT NOT NULL DEFAULT (datetime('now')),
		updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
	);

CREATE TABLE pulse_jobs (
    id              TEXT PRIMARY KEY,                 -- e.g. "wing-base:rotate-wing-db-backup"
    plugin_name     TEXT NOT NULL,                    -- owning plugin (FK soft)
    job_name        TEXT NOT NULL,                    -- unique within plugin
    runner          TEXT NOT NULL DEFAULT 'subprocess', -- subprocess | agent (A8)
    command         TEXT NOT NULL,
    args_json       TEXT NOT NULL DEFAULT '[]',       -- JSON array
    env_json        TEXT NOT NULL DEFAULT '{}',       -- JSON map (string→string)
    schedule        TEXT NOT NULL,                    -- cron expression
    jitter_min      INTEGER NOT NULL DEFAULT 0,
    max_runtime_s   INTEGER NOT NULL DEFAULT 300,
    max_concurrent  INTEGER NOT NULL DEFAULT 1,
    paused          INTEGER NOT NULL DEFAULT 0,       -- 0/1; manual operator pause
    paused_reason   TEXT,                             -- nullable
    next_fire_at    TEXT,                             -- ISO-8601; computed Wing-side
    last_fired_at   TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    removed_at      TEXT                              -- soft-delete (plugin removal)
);

CREATE TABLE pulse_runs (
    run_id          TEXT PRIMARY KEY,                 -- UUID4
    job_id          TEXT NOT NULL,                    -- FK soft → pulse_jobs.id
    fired_at        TEXT NOT NULL,                    -- ISO-8601
    finished_at     TEXT,                             -- nullable until finish
    exit_code       INTEGER,                          -- nullable until finish (-9 = SIGKILL/timeout, 127 = no such command)
    duration_ms     INTEGER,                          -- nullable until finish
    stdout_tail     TEXT,                             -- last 2000 chars
    stderr_tail     TEXT,
    actor_id        TEXT,                             -- Authentik client_id of pulse instance
    actor_action_id TEXT,                             -- A10: UUID grouping start/finish events with this run
    acted_at        TEXT,                             -- A10: wall-clock time the action was initiated (usually = fired_at)
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE remediation_items (
		id                  TEXT PRIMARY KEY,
		finding_ref         TEXT,
		component_id        TEXT,
		severity            TEXT NOT NULL CHECK (severity IN ('CRITICAL','HIGH','MEDIUM','LOW')),
		current_version     TEXT,
		fix_version         TEXT,
		remediation_type    TEXT,
		remediation_detail  TEXT,
		status              TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','resolved','wontfix')),
		auto_fixable        INTEGER NOT NULL DEFAULT 0,
		source              TEXT,
		confidence          TEXT DEFAULT 'medium',
		found_at            TEXT NOT NULL DEFAULT (datetime('now')),
		resolved_at         TEXT,
		resolved_by         TEXT,
		scan_cycle          INTEGER,
		created_at          TEXT NOT NULL DEFAULT (datetime('now')),
		updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
	);

CREATE TABLE report_types (
		id              TEXT PRIMARY KEY,
		name            TEXT NOT NULL,
		api_namespace   TEXT NOT NULL UNIQUE,
		table_name      TEXT NOT NULL,
		template        TEXT,
		enabled         INTEGER NOT NULL DEFAULT 1,
		created_at      TEXT NOT NULL DEFAULT (datetime('now'))
	);

CREATE TABLE scan_config (
		id                              INTEGER PRIMARY KEY CHECK (id = 1),
		batch_size                      INTEGER NOT NULL DEFAULT 5,
		schedule                        TEXT NOT NULL DEFAULT '2x daily (06:00, 18:00)',
		strategy                        TEXT NOT NULL DEFAULT 'oldest_first',
		cve_refresh_interval_hours      INTEGER NOT NULL DEFAULT 24,
		misconfig_refresh_interval_days INTEGER NOT NULL DEFAULT 7,
		attack_probe_rotation_size      INTEGER NOT NULL DEFAULT 8,
		scanner_version                 TEXT NOT NULL DEFAULT '1.0.0',
		initialized_at                  TEXT NOT NULL DEFAULT (datetime('now')),
		last_full_scan                  TEXT,
		last_advisory_check             TEXT,
		last_remediation_applied        TEXT,
		next_batch                      TEXT
	);

CREATE TABLE scan_cycles (
		id                  INTEGER PRIMARY KEY AUTOINCREMENT,
		cycle_number        INTEGER NOT NULL UNIQUE,
		started_at          TEXT NOT NULL DEFAULT (datetime('now')),
		completed_at        TEXT,
		batch_components    TEXT,
		notes               TEXT
	);

CREATE TABLE systems (
		id              TEXT PRIMARY KEY,
		parent_id       TEXT REFERENCES systems(id) ON DELETE SET NULL,
		name            TEXT NOT NULL,
		description     TEXT,
		type            TEXT NOT NULL DEFAULT 'docker',
		category        TEXT NOT NULL DEFAULT 'service',
		stack           TEXT,
		image           TEXT,
		version         TEXT,
		version_var     TEXT,
		pinned          INTEGER NOT NULL DEFAULT 1,

		-- Network
		domain          TEXT,
		port            INTEGER,
		url             TEXT,
		-- W6.4 (2026-06-10): probe target when it differs from the card link.
		-- Backend services (Prometheus, Loki, MariaDB, …) have no public url
		-- but DO have a loopback health endpoint; tcp://host:port = TCP-only
		-- liveness for DB-class services the HTTP probe can't reach.
		health_url      TEXT,
		network_exposed INTEGER NOT NULL DEFAULT 0,
		has_web_ui      INTEGER NOT NULL DEFAULT 0,

		-- Ansible integration
		toggle_var      TEXT,
		enabled         INTEGER NOT NULL DEFAULT 1,

		-- Security & scanning
		priority        TEXT NOT NULL DEFAULT 'medium',
		upstream_repo   TEXT,

		-- Health (updated by probes)
		health_status   TEXT NOT NULL DEFAULT 'unknown',
		health_http_code INTEGER,
		health_ms       INTEGER,
		health_checked_at TEXT,

		-- Provenance
		source          TEXT NOT NULL DEFAULT 'manual',

		created_at      TEXT NOT NULL DEFAULT (datetime('now')),
		updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
	);

CREATE TABLE upgrade_recipes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    service       TEXT NOT NULL,
    recipe_id     TEXT NOT NULL,
    from_pattern  TEXT,                     -- from_regex in the recipe
    to_version    TEXT,                     -- the target version
    severity      TEXT,                     -- patch | minor | breaking
    docs_url      TEXT,
    title         TEXT,
    coexistence_supported INTEGER NOT NULL DEFAULT 0,  -- the recipe's coexistence_supported flag (B4b plan-choice option (b) gate)
    reset_json    TEXT,                     -- AUTHORED reset block JSON (scope/estimated_sec/affected_services/...) from upgrades/<svc>.yml, stored verbatim; NOT derived — the engine's resolve_reset derives the floor at apply time. NULL = no authored reset (UI shows 'container' floor). Mirrors coexistence_supported.
    ingested_at   TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (service, recipe_id)
);

CREATE TABLE upgrades_applied (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    service           TEXT NOT NULL,
    recipe_id         TEXT NOT NULL,
    from_version      TEXT,
    to_version        TEXT,
    severity          TEXT,
    applied_at        TEXT NOT NULL,
    success           INTEGER NOT NULL,
    duration_sec      INTEGER,
    rolled_back       INTEGER NOT NULL DEFAULT 0,
    event_run_id      TEXT,
    raw_record_json   TEXT
);

CREATE TABLE upgrades_planned (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    service       TEXT NOT NULL,
    recipe_id     TEXT NOT NULL,
    target_version TEXT,
    planned_by    TEXT NOT NULL DEFAULT 'operator',
    status        TEXT NOT NULL DEFAULT 'planned',   -- planned | applied | cancelled
    notes         TEXT,
    reset_scope   TEXT,                                 -- resolved reset.scope at plan time (none|container|stack|host_app|host_reboot)
    session_risk  INTEGER NOT NULL DEFAULT 0,           -- derived: reset_scope in {host_app,host_reboot}
    run_mode      TEXT NOT NULL DEFAULT 'attached',     -- attached | detached | stage_then_reboot
    planned_at    TEXT NOT NULL DEFAULT (datetime('now')),
    applied_at    TEXT, plan_mode TEXT NOT NULL DEFAULT 'migration', coexistence_planned_id INTEGER, migration_uuid TEXT, plan_choice_at TEXT,
    UNIQUE (service, recipe_id, status)
);

CREATE TABLE user_invitations (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid                TEXT NOT NULL UNIQUE,           -- local UUID4 minted at insert
    invitation_pk       TEXT NOT NULL UNIQUE,           -- Authentik invitation primary key (UUID)
    invitation_url      TEXT NOT NULL,                  -- full https://auth.<tld>/if/flow/.../?itoken=<pk>
    email_hint          TEXT,                           -- optional recipient hint (display only)
    name_hint           TEXT,                           -- optional display name for the invite (UI surface)
    tenant              TEXT NOT NULL DEFAULT 'default',-- multi-tenant slug; one Authentik install can host multiple
    target_groups_json  TEXT NOT NULL DEFAULT '[]',     -- JSON array of Authentik group names (RBAC tier(s))
    target_apps_json    TEXT NOT NULL DEFAULT '[]',     -- JSON array of {slug, role} objects; informational
    expires_at          TEXT NOT NULL,                  -- ISO8601 absolute expiry; Authentik enforces
    single_use          INTEGER NOT NULL DEFAULT 1,     -- mirrors Authentik invitation.single_use
    redeemed_at         TEXT,                           -- NULL until /api/v3 webhook (or operator) marks redeemed
    redeemed_user_pk    TEXT,                           -- Authentik user PK of the redeemer (if known)
    revoked_at          TEXT,                           -- NULL until operator revokes (deletes Authentik side)
    actor_id            TEXT NOT NULL,                  -- A10: operator who issued the invite
    actor_action_id     TEXT,                           -- A10: groups with /events row of the issue action
    metadata_json       TEXT NOT NULL DEFAULT '{}',     -- free-form (e.g. inviter note, source presenter)
    provisioning_json   TEXT NOT NULL DEFAULT '{}',     -- A18 Cesta B: Infisical + Stalwart provisioning result snapshot
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE users (
		id              INTEGER PRIMARY KEY AUTOINCREMENT,
		username        TEXT NOT NULL UNIQUE,
		email           TEXT,
		display_name    TEXT,
		groups          TEXT,
		last_login      TEXT,
		created_at      TEXT NOT NULL DEFAULT (datetime('now'))
	);

-- ============================================================
-- VIEWS (1)
-- ============================================================

CREATE VIEW components AS
		SELECT id, name, category, stack, image, version_var,
			   version AS default_version, pinned, network_exposed, has_web_ui,
			   priority, upstream_repo, port, domain, created_at, updated_at
		FROM systems;

-- ============================================================
-- INDEXS (83)
-- ============================================================

CREATE INDEX idx_adv_date ON advisories(date);

CREATE INDEX idx_agent_credentials_scope    ON agent_credentials(scope);

CREATE INDEX idx_agent_iterations_result   ON agent_iterations(grader_result);

CREATE INDEX idx_agent_sessions_agent_name ON agent_sessions(agent_name);

CREATE INDEX idx_agent_sessions_started_at ON agent_sessions(started_at);

CREATE INDEX idx_agent_sessions_status     ON agent_sessions(status);

CREATE INDEX idx_agent_sessions_trace_id   ON agent_sessions(trace_id);

CREATE INDEX idx_agent_sessions_trigger    ON agent_sessions(trigger, trigger_id);

CREATE INDEX idx_agent_subscriptions_enabled ON agent_subscriptions(enabled);

CREATE INDEX idx_agent_threads_parent  ON agent_threads(parent_thread_uuid);

CREATE INDEX idx_agent_threads_session ON agent_threads(session_uuid);

CREATE INDEX idx_agent_threads_status  ON agent_threads(status);

CREATE INDEX idx_coexist_active  ON coexistence_tracks(active);

CREATE INDEX idx_coexist_service ON coexistence_tracks(service);

CREATE INDEX idx_coexistence_planned_status ON coexistence_planned (status);

CREATE INDEX idx_events_actor_action_id ON events(actor_action_id);

CREATE INDEX idx_events_actor_id        ON events(actor_id);

CREATE INDEX idx_events_migration ON events(migration_id);

CREATE INDEX idx_events_patch     ON events(patch_id);

CREATE INDEX idx_events_row_hash ON events(row_hash);

CREATE INDEX idx_events_run_id    ON events(run_id);

CREATE INDEX idx_events_source    ON events(source);

CREATE INDEX idx_events_ts        ON events(ts);

CREATE INDEX idx_events_type      ON events(type);

CREATE INDEX idx_events_upgrade   ON events(upgrade_id);

CREATE INDEX idx_gdpr_breaches_status ON gdpr_breaches(status, detected_at);

CREATE INDEX idx_gdpr_consent_active ON gdpr_consent(subject_email, activity) WHERE withdrawn_at IS NULL;

CREATE INDEX idx_gdpr_consent_activity   ON gdpr_consent(activity);

CREATE INDEX idx_gdpr_consent_processing ON gdpr_consent(processing_id);

CREATE INDEX idx_gdpr_consent_subject    ON gdpr_consent(subject_email);

CREATE INDEX idx_gdpr_dsar_email  ON gdpr_dsar(subject_email);

CREATE INDEX idx_gdpr_dsar_status ON gdpr_dsar(status);

CREATE INDEX idx_gitleaks_rule_id           ON gitleaks_findings(rule_id);

CREATE INDEX idx_gitleaks_scan_id           ON gitleaks_findings(scan_id);

CREATE INDEX idx_gitleaks_severity          ON gitleaks_findings(severity, resolved_at);

CREATE INDEX idx_memory_agent_name ON agent_memory_stores (agent_name);

CREATE INDEX idx_memory_updated    ON agent_memory_stores (updated_at);

CREATE INDEX idx_mig_authored_service ON migrations_authored (service);

CREATE INDEX idx_mig_authored_session ON migrations_authored (session_uuid);

CREATE INDEX idx_mig_authored_status  ON migrations_authored (review_status);

CREATE INDEX idx_migrations_applied_at ON migrations_applied(applied_at);

CREATE INDEX idx_migrations_severity   ON migrations_applied(severity);

CREATE INDEX idx_notifications_actor_action ON notifications(actor_action_id);

CREATE INDEX idx_notifications_created_at   ON notifications(created_at);

CREATE INDEX idx_notifications_mail_digest  ON notifications(mail_digest_window) WHERE mail_digest_window IS NOT NULL AND mail_dispatched_at IS NULL;

CREATE INDEX idx_notifications_mail_pending ON notifications(mail_dispatched_at) WHERE mail_dispatched_at IS NULL;

CREATE INDEX idx_notifications_ntfy_pending ON notifications(ntfy_dispatched_at) WHERE ntfy_dispatched_at IS NULL;

CREATE INDEX idx_notifications_severity     ON notifications(severity);

CREATE INDEX idx_notifications_unread       ON notifications(target_actor_id, wing_inbox_read_at);

CREATE INDEX idx_pap_target ON pentest_areas_planned(target_id);

CREATE INDEX idx_pat_target ON pentest_areas_tested(target_id);

CREATE INDEX idx_patches_applied_at    ON patches_applied(applied_at);

CREATE INDEX idx_patches_applied_comp  ON patches_applied(component_id);

CREATE INDEX idx_patches_applied_patch ON patches_applied(patch_id);

CREATE INDEX idx_pf_discovered_by ON pentest_findings(discovered_by);

CREATE INDEX idx_pf_resolved_at ON pentest_findings(resolved_at) WHERE resolved_at IS NULL;

CREATE INDEX idx_pt_created_by ON pentest_targets(created_by);

CREATE INDEX idx_pulse_jobs_due        ON pulse_jobs(paused, next_fire_at);

CREATE INDEX idx_pulse_jobs_plugin     ON pulse_jobs(plugin_name);

CREATE INDEX idx_pulse_runs_actor_action_id   ON pulse_runs(actor_action_id);

CREATE INDEX idx_pulse_runs_fired_at          ON pulse_runs(fired_at);

CREATE INDEX idx_pulse_runs_job_id            ON pulse_runs(job_id);

CREATE INDEX idx_rem_component ON remediation_items(component_id);

CREATE INDEX idx_rem_severity ON remediation_items(severity);

CREATE INDEX idx_rem_status ON remediation_items(status);

CREATE INDEX idx_sys_category ON systems(category);

CREATE INDEX idx_sys_health ON systems(health_status);

CREATE INDEX idx_sys_parent ON systems(parent_id);

CREATE INDEX idx_sys_stack ON systems(stack);

CREATE INDEX idx_upgrade_recipes_service ON upgrade_recipes (service);

CREATE INDEX idx_upgrades_applied_at ON upgrades_applied(applied_at);

CREATE INDEX idx_upgrades_planned_status ON upgrades_planned (status);

CREATE INDEX idx_upgrades_service ON upgrades_applied(service);

CREATE INDEX idx_user_inv_actor       ON user_invitations(actor_id);

CREATE INDEX idx_user_inv_created     ON user_invitations(created_at);

CREATE INDEX idx_user_inv_expires     ON user_invitations(expires_at) WHERE redeemed_at IS NULL AND revoked_at IS NULL;

CREATE INDEX idx_user_inv_redeemed    ON user_invitations(redeemed_at);

CREATE INDEX idx_user_inv_tenant      ON user_invitations(tenant);

CREATE UNIQUE INDEX uq_agent_credentials   ON agent_credentials(vault_id, scope);

CREATE UNIQUE INDEX uq_agent_iterations    ON agent_iterations(session_uuid, iteration);

CREATE UNIQUE INDEX uq_coexist_one_primary ON coexistence_tracks (service) WHERE role = 'primary';

CREATE UNIQUE INDEX uq_gitleaks_fingerprint ON gitleaks_findings(fingerprint);

CREATE UNIQUE INDEX uq_pulse_jobs_name ON pulse_jobs(plugin_name, job_name);

-- ============================================================
-- TRIGGERS (2)
-- ============================================================

CREATE TRIGGER events_worm_delete BEFORE DELETE ON events FOR EACH ROW
  WHEN OLD.row_hash IS NOT NULL
   AND COALESCE((SELECT v FROM audit_chain_meta WHERE k='purge_unlocked'), '0') <> '1'
  BEGIN SELECT RAISE(ABORT, 'events WORM: DELETE only via the retention re-anchor path'); END;

CREATE TRIGGER events_worm_update BEFORE UPDATE ON events FOR EACH ROW
  WHEN OLD.row_hash IS NOT NULL AND (
       NEW.ts IS NOT OLD.ts OR NEW.run_id IS NOT OLD.run_id OR NEW.type IS NOT OLD.type
    OR NEW.playbook IS NOT OLD.playbook OR NEW.play IS NOT OLD.play OR NEW.task IS NOT OLD.task
    OR NEW.role IS NOT OLD.role OR NEW.host IS NOT OLD.host OR NEW.duration_ms IS NOT OLD.duration_ms
    OR NEW.changed IS NOT OLD.changed OR NEW.result_json IS NOT OLD.result_json
    OR NEW.migration_id IS NOT OLD.migration_id OR NEW.upgrade_id IS NOT OLD.upgrade_id
    OR NEW.patch_id IS NOT OLD.patch_id OR NEW.coexist_svc IS NOT OLD.coexist_svc
    OR NEW.source IS NOT OLD.source OR NEW.actor_id IS NOT OLD.actor_id OR NEW.acted_at IS NOT OLD.acted_at
    OR NEW.row_hash IS NOT OLD.row_hash OR NEW.prev_hash IS NOT OLD.prev_hash)
  BEGIN SELECT RAISE(ABORT, 'events WORM: only actor_action_id may change on a chained row'); END;

