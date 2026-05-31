-- Wing schema extensions for the nOS State & Migration Framework.
-- Applied idempotently by bin/init-db.php after the base schema. Safe to
-- re-run: all statements use CREATE ... IF NOT EXISTS.

-- Events from the Ansible callback plugin (agent 3).
-- NOTE: for already-initialized DBs, bin/init-db.php performs an idempotent
-- ALTER TABLE ADD COLUMN sweep to add patch_id / any future typed ids.
CREATE TABLE IF NOT EXISTS events (
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
CREATE INDEX IF NOT EXISTS idx_events_run_id    ON events(run_id);
CREATE INDEX IF NOT EXISTS idx_events_ts        ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_type      ON events(type);
CREATE INDEX IF NOT EXISTS idx_events_migration ON events(migration_id);
CREATE INDEX IF NOT EXISTS idx_events_upgrade   ON events(upgrade_id);
CREATE INDEX IF NOT EXISTS idx_events_patch     ON events(patch_id);
CREATE INDEX IF NOT EXISTS idx_events_source    ON events(source);
CREATE INDEX IF NOT EXISTS idx_events_actor_id        ON events(actor_id);
CREATE INDEX IF NOT EXISTS idx_events_actor_action_id ON events(actor_action_id);
CREATE INDEX IF NOT EXISTS idx_events_row_hash        ON events(row_hash);

-- Audit-chain metadata singleton (k/v). Keys:
--   purge_unlocked              '0'/'1' guard the WORM DELETE trigger checks
--   last_purged_hash / _cutoff  retention boundary (survivor's prev_hash anchor)
--   chain_last_anchor           current tail recorded by backfill-event-chain.php
--   chain_segment_anchor_<hash> a re-enable boundary the verifier accepts
--   last_verify_ok / _at        cached /audit badge verdict (future Pulse job)
CREATE TABLE IF NOT EXISTS audit_chain_meta (
    k  TEXT PRIMARY KEY,
    v  TEXT
);
INSERT OR IGNORE INTO audit_chain_meta (k, v) VALUES ('purge_unlocked', '0');

-- Column-scoped WORM triggers. UNCONDITIONAL (installed always) but fire ONLY
-- on already-CHAINED rows (OLD.row_hash NOT NULL). On a chain-off install every
-- row has NULL row_hash, so these never fire -> byte-identical write semantics,
-- and the CI-rebuilt contracts artifact is flag-independent.
--
-- UPDATE: allow ONLY actor_action_id to change (the two AgentSessionRepository
-- back-stamps touch only that column); abort if any HASHED column changes.
DROP TRIGGER IF EXISTS events_worm_update;
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

-- DELETE: blocked on chained rows unless purge_unlocked='1' (set only inside
-- purge-events.php's re-anchor transaction; reset immediately after + on every
-- init-db boot).
DROP TRIGGER IF EXISTS events_worm_delete;
CREATE TRIGGER events_worm_delete BEFORE DELETE ON events FOR EACH ROW
  WHEN OLD.row_hash IS NOT NULL
   AND COALESCE((SELECT v FROM audit_chain_meta WHERE k='purge_unlocked'), '0') <> '1'
  BEGIN SELECT RAISE(ABORT, 'events WORM: DELETE only via the retention re-anchor path'); END;

-- Migration history mirror. Source of truth lives in ~/.nos/state.yml; this
-- table is a read cache populated via BoxAPI /api/state pushes.
CREATE TABLE IF NOT EXISTS migrations_applied (
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
CREATE INDEX IF NOT EXISTS idx_migrations_applied_at ON migrations_applied(applied_at);
CREATE INDEX IF NOT EXISTS idx_migrations_severity   ON migrations_applied(severity);

-- Upgrade history. Each apply/rollback produces one row.
CREATE TABLE IF NOT EXISTS upgrades_applied (
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
CREATE INDEX IF NOT EXISTS idx_upgrades_service ON upgrades_applied(service);
CREATE INDEX IF NOT EXISTS idx_upgrades_applied_at ON upgrades_applied(applied_at);

-- Coexistence tracks mirror (shape matches ~/.nos/state.yml coexistence block).
CREATE TABLE IF NOT EXISTS coexistence_tracks (
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
    updated_at    TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(service, tag)
);
CREATE INDEX IF NOT EXISTS idx_coexist_service ON coexistence_tracks(service);
CREATE INDEX IF NOT EXISTS idx_coexist_active  ON coexistence_tracks(active);

-- Patch apply history. Each apply/rollback produces one row. Mirrors
-- upgrades_applied so the UI can render a unified "maintenance timeline".
-- Source of truth is ~/.nos/state.yml patches_applied[] populated by the
-- apply-patches engine; this table is a BoxAPI-pushed read cache.
CREATE TABLE IF NOT EXISTS patches_applied (
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
CREATE INDEX IF NOT EXISTS idx_patches_applied_patch ON patches_applied(patch_id);
CREATE INDEX IF NOT EXISTS idx_patches_applied_at    ON patches_applied(applied_at);
CREATE INDEX IF NOT EXISTS idx_patches_applied_comp  ON patches_applied(component_id);

-- ── GDPR Article 30 register (Track D, 2026-04-26) ─────────────────────
-- Each row is one entry in the "register of processing activities" required
-- of EU operators by GDPR Art. 30. Wing's /gdpr UI renders these as a CSV-
-- exportable table. Authoritative seed data ships in
-- files/project-wing/db/gdpr-seed.sql; operators add custom processing
-- activities by inserting more rows.
CREATE TABLE IF NOT EXISTS gdpr_processing (
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

-- Data Subject Access Request log. CNIL inspections check that DSAR responses
-- are tracked. Each row records an incoming request and its disposition.
CREATE TABLE IF NOT EXISTS gdpr_dsar (
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
CREATE INDEX IF NOT EXISTS idx_gdpr_dsar_email  ON gdpr_dsar(subject_email);
CREATE INDEX IF NOT EXISTS idx_gdpr_dsar_status ON gdpr_dsar(status);

-- Personal data breach register (GDPR Art. 33-34). Inspectors expect a log
-- even if zero entries — proves the operator considered the question.
CREATE TABLE IF NOT EXISTS gdpr_breaches (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    detected_at         TEXT NOT NULL,
    notified_supervisor_at TEXT,                    -- 72h deadline tracker
    notified_subjects_at   TEXT,                    -- when "high risk"
    nature              TEXT NOT NULL,              -- short headline
    affected_subjects   INTEGER,
    likely_consequences TEXT,
    measures_taken      TEXT,
    status              TEXT NOT NULL,              -- detected | notified | resolved | non-reportable
    notes               TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================================
-- Pulse — scheduled-job catalog + run history (Anatomy A4, 2026-05-03)
-- ============================================================================
-- pulse_jobs: registered jobs (one row per (plugin_name, job_name)).
-- Owned by plugin loader (files/anatomy/module_utils/load_plugins.py); operators
-- may pause/resume via the Wing UI without touching the playbook.
--
-- Pulse polls /api/v1/pulse_jobs/due (server computes next_fire_at from
-- schedule + jitter) — Pulse itself stays dumb about cron syntax.

CREATE TABLE IF NOT EXISTS pulse_jobs (
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
CREATE INDEX IF NOT EXISTS idx_pulse_jobs_plugin     ON pulse_jobs(plugin_name);
CREATE INDEX IF NOT EXISTS idx_pulse_jobs_due        ON pulse_jobs(paused, next_fire_at);
CREATE UNIQUE INDEX IF NOT EXISTS uq_pulse_jobs_name ON pulse_jobs(plugin_name, job_name);

-- pulse_runs: per-execution history. Pulse POSTs run_start (creates row)
-- + run_finish (UPDATE on run_id). Audit-relevant — actor_id-tagged for
-- the per-actor identity work in §11 of the refactor doc.
CREATE TABLE IF NOT EXISTS pulse_runs (
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
CREATE INDEX IF NOT EXISTS idx_pulse_runs_job_id            ON pulse_runs(job_id);
CREATE INDEX IF NOT EXISTS idx_pulse_runs_fired_at          ON pulse_runs(fired_at);
CREATE INDEX IF NOT EXISTS idx_pulse_runs_actor_action_id   ON pulse_runs(actor_action_id);

-- gitleaks_findings: secret-scanning findings ingested by the gitleaks plugin.
-- Anatomy A7 (2026-05-06). The gitleaks plugin (files/anatomy/plugins/gitleaks/)
-- runs nightly via Pulse (runner=subprocess) and POSTs findings in batch to
-- /api/v1/gitleaks_findings. Wing deduplicates on fingerprint (gitleaks'
-- unique key per commit+file+line+rule); resolved_at is preserved across
-- re-scans. scan_id soft-FK → pulse_runs.run_id (NULL for ad-hoc runs).

CREATE TABLE IF NOT EXISTS gitleaks_findings (
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
CREATE UNIQUE INDEX IF NOT EXISTS uq_gitleaks_fingerprint ON gitleaks_findings(fingerprint);
CREATE INDEX IF NOT EXISTS idx_gitleaks_rule_id           ON gitleaks_findings(rule_id);
CREATE INDEX IF NOT EXISTS idx_gitleaks_severity          ON gitleaks_findings(severity, resolved_at);
CREATE INDEX IF NOT EXISTS idx_gitleaks_scan_id           ON gitleaks_findings(scan_id);

-- ============================================================================
-- Notifications — operator-attention fanout (Anatomy A9, 2026-05-16)
-- ============================================================================
-- One row per notification. Wing /inbox renders unread rows for the target
-- actor; the dispatch worker (bin/dispatch-notifications.php) reads pending
-- rows where the channel is listed but the *_dispatched_at column is NULL,
-- delivers per channel, and writes back the timestamp.
--
-- Severity routing comes from the originating plugin/agent manifest's
-- `notification:` block; the aggregator (A9.5) precomputes the channel list
-- at emission time so the dispatcher stays dumb. Default for any emission
-- without a manifest mapping is wing-inbox-only (severity-agnostic).
--
-- A10 actor audit: actor_id + actor_action_id mirror events; a single
-- agent_action_id groups the source event (e.g. gitleaks_finding_high) with
-- its derived notification(s) so /audit reconstructs the lineage.

CREATE TABLE IF NOT EXISTS notifications (
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
CREATE INDEX IF NOT EXISTS idx_notifications_unread       ON notifications(target_actor_id, wing_inbox_read_at);
CREATE INDEX IF NOT EXISTS idx_notifications_severity     ON notifications(severity);
CREATE INDEX IF NOT EXISTS idx_notifications_actor_action ON notifications(actor_action_id);
CREATE INDEX IF NOT EXISTS idx_notifications_created_at   ON notifications(created_at);
CREATE INDEX IF NOT EXISTS idx_notifications_ntfy_pending ON notifications(ntfy_dispatched_at) WHERE ntfy_dispatched_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_notifications_mail_pending ON notifications(mail_dispatched_at) WHERE mail_dispatched_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_notifications_mail_digest  ON notifications(mail_digest_window) WHERE mail_digest_window IS NOT NULL AND mail_dispatched_at IS NULL;

-- ============================================================================
-- User invitations (Anatomy A15, 2026-05-17)
-- ============================================================================
-- Operator-issued Authentik invitations with per-invite app + tier metadata.
-- One row per invite minted from Wing's /users/invite UI. The invite is
-- created on the Authentik side via POST /api/v3/stages/invitation/invitations/;
-- the Authentik-side primary-key (UUID) lives in invitation_pk and the
-- shareable URL in invitation_url. fixed_data on the Authentik invitation
-- carries the target_groups list so the enrollment flow's group-bind
-- expression policy can attach the new user to the right RBAC tier(s) +
-- per-tenant scopes during signup.
--
-- target_apps_json + target_groups_json are persisted here separately
-- (rather than only on the Authentik side) so /users/invitations can
-- show an operator-readable audit trail even if the invite was redeemed,
-- expired, or revoked on the Authentik side. actor_id holds the
-- operator's Authentik client_id (from forward-auth headers); A10
-- lineage applies.

CREATE TABLE IF NOT EXISTS user_invitations (
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
CREATE INDEX IF NOT EXISTS idx_user_inv_actor       ON user_invitations(actor_id);
CREATE INDEX IF NOT EXISTS idx_user_inv_tenant      ON user_invitations(tenant);
CREATE INDEX IF NOT EXISTS idx_user_inv_expires     ON user_invitations(expires_at) WHERE redeemed_at IS NULL AND revoked_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_user_inv_redeemed    ON user_invitations(redeemed_at);
CREATE INDEX IF NOT EXISTS idx_user_inv_created     ON user_invitations(created_at);

-- ============================================================================
-- AgentKit — AIT runtime (Anatomy A14, 2026-05-07)
-- ============================================================================
-- Five tables for the platform-agnostic, audit-first agent runtime. Every row
-- here corresponds to a real LLM-call lineage: who decided, what they decided,
-- what they did, what came out. Joinable to events.actor_action_id so the
-- A10 actor audit story stays unified across operator + agent + Pulse runs.
--
-- Naming convention (locked by tests/anatomy/test_agentkit_naming.py):
--   * Tables prefixed agent_*
--   * UUIDs in `uuid` columns; integer PKs everywhere for join speed
--   * trace_id / span_id columns are W3C Trace Context (32-hex / 16-hex)
--   * actor_id mirrors events.actor_id; actor_action_id groups all events
--     emitted within one agent session

-- agent_sessions: one row per agent invocation (Pulse-fired, webhook-fired,
-- operator-fired). Mirrors Anthropic Managed Agents `session` semantics but
-- everything stays in wing.db so OpenClaw / future local LLMs slot in.
CREATE TABLE IF NOT EXISTS agent_sessions (
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
CREATE INDEX IF NOT EXISTS idx_agent_sessions_agent_name ON agent_sessions(agent_name);
CREATE INDEX IF NOT EXISTS idx_agent_sessions_status     ON agent_sessions(status);
CREATE INDEX IF NOT EXISTS idx_agent_sessions_trigger    ON agent_sessions(trigger, trigger_id);
CREATE INDEX IF NOT EXISTS idx_agent_sessions_started_at ON agent_sessions(started_at);
CREATE INDEX IF NOT EXISTS idx_agent_sessions_trace_id   ON agent_sessions(trace_id);

-- agent_threads: child threads spawned by a coordinator. Solo agents have one
-- thread (the primary); coordinators may spawn multiple. Mirrors Anthropic's
-- session_thread; parent_thread_uuid is null for the primary thread.
CREATE TABLE IF NOT EXISTS agent_threads (
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
CREATE INDEX IF NOT EXISTS idx_agent_threads_session ON agent_threads(session_uuid);
CREATE INDEX IF NOT EXISTS idx_agent_threads_parent  ON agent_threads(parent_thread_uuid);
CREATE INDEX IF NOT EXISTS idx_agent_threads_status  ON agent_threads(status);

-- agent_iterations: outcome-driven iteration loop. One row per grader call.
-- Empty for non-outcome sessions. iteration is 0-indexed; max defined by
-- agent.yml::outcomes.max_iterations.
CREATE TABLE IF NOT EXISTS agent_iterations (
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
CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_iterations    ON agent_iterations(session_uuid, iteration);
CREATE INDEX IF NOT EXISTS idx_agent_iterations_result   ON agent_iterations(grader_result);

-- agent_vaults: per-purpose credential bag. Borrowed from Anthropic Managed
-- Agents pattern, scoped to nOS. Plaintext NEVER stored here — secret_ref
-- is a pointer (Infisical path or env var name) resolved at session-open
-- time by App\AgentKit\Vault\CredentialResolver.
CREATE TABLE IF NOT EXISTS agent_vaults (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid            TEXT NOT NULL UNIQUE,
    name            TEXT NOT NULL UNIQUE,             -- e.g. "conductor-default", "code-reviewer-org-acme"
    display_name    TEXT NOT NULL,
    metadata_json   TEXT NOT NULL DEFAULT '{}',
    archived_at     TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS agent_credentials (
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
CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_credentials   ON agent_credentials(vault_id, scope);
CREATE INDEX IF NOT EXISTS idx_agent_credentials_scope    ON agent_credentials(scope);

-- agent_subscriptions: outbound webhook receivers. Wing fires HMAC-signed
-- POSTs on agent lifecycle events; subscribers acknowledge with 2xx.
-- Mirrors Anthropic webhooks shape (event.id / event.type / data.id /
-- data.type) so external tooling that supports Anthropic webhooks already
-- understands ours.
CREATE TABLE IF NOT EXISTS agent_subscriptions (
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
CREATE INDEX IF NOT EXISTS idx_agent_subscriptions_enabled ON agent_subscriptions(enabled);

-- agent_memory_stores: deduplicated memory entries produced by the Dreams
-- consolidation cycle (post-A14 follow-up B-Dreams, 2026-05-07). Each row is
-- one consolidated memory fact for an agent — a markdown / text body distilled
-- from recent agent_sessions. The dream cycle (bin/dream-agent.php) reads the
-- last N sessions for an agent + the current store, runs the agent under a
-- restricted "dream" tool roster (read-only — no bash, no mcp_wing write
-- endpoints), and produces an updated, deduplicated store.
--
-- Plaintext: memory entries are NOT secrets. They DO carry task context that
-- can include operator notes, so telemetry SHOULD log only (uuid, title,
-- length) — never the full body. Same sensitivity profile as event text.
--
-- source_session_uuid soft-FKs agent_sessions.uuid (the session that produced
-- or last updated the entry). trace_id is the W3C trace_id for cross-link
-- with Tempo.
CREATE TABLE IF NOT EXISTS agent_memory_stores (
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
CREATE INDEX IF NOT EXISTS idx_memory_agent_name ON agent_memory_stores (agent_name);
CREATE INDEX IF NOT EXISTS idx_memory_updated    ON agent_memory_stores (updated_at);

-- ── Upgrade pipeline (W5-B, 2026-05-26) ─────────────────────────────────────
-- upgrade_recipes: the version-transition catalog, ingested from
-- upgrades/*.yml by bin/ingest-upgrade-recipes.php (offline / deterministic —
-- no upstream calls). Feeds the /upgrades version matrix.
CREATE TABLE IF NOT EXISTS upgrade_recipes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    service       TEXT NOT NULL,
    recipe_id     TEXT NOT NULL,
    from_pattern  TEXT,                     -- from_regex in the recipe
    to_version    TEXT,                     -- the target version
    severity      TEXT,                     -- patch | minor | breaking
    docs_url      TEXT,
    title         TEXT,
    ingested_at   TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (service, recipe_id)
);
CREATE INDEX IF NOT EXISTS idx_upgrade_recipes_service ON upgrade_recipes (service);

-- upgrades_planned: operator/agent-queued upgrades. The upgrade-engine
-- (tasks/upgrade-engine.yml) consumes status='planned' rows ONLY under
-- --tags upgrade (never on a normal run), applies the recipe, then flips the
-- row to 'applied'. planned_by carries the attribution (operator/agent name).
CREATE TABLE IF NOT EXISTS upgrades_planned (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    service       TEXT NOT NULL,
    recipe_id     TEXT NOT NULL,
    target_version TEXT,
    planned_by    TEXT NOT NULL DEFAULT 'operator',
    status        TEXT NOT NULL DEFAULT 'planned',   -- planned | applied | cancelled
    notes         TEXT,
    planned_at    TEXT NOT NULL DEFAULT (datetime('now')),
    applied_at    TEXT,
    UNIQUE (service, recipe_id, status)
);
CREATE INDEX IF NOT EXISTS idx_upgrades_planned_status ON upgrades_planned (status);

-- coexistence_planned: operator/agent-queued coexistence provisions (W5-B5).
-- The upgrade-architect agent queues a parallel-track provision for a
-- breaking / whole-new-version upgrade; the consumer applies it ONLY under
-- --tags coexistence (never on a normal run), then flips to 'applied'.
CREATE TABLE IF NOT EXISTS coexistence_planned (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    service       TEXT NOT NULL,
    tag           TEXT NOT NULL DEFAULT 'new',
    target_version TEXT,
    port_offset   INTEGER DEFAULT 10,
    reason        TEXT,
    planned_by    TEXT NOT NULL DEFAULT 'operator',
    status        TEXT NOT NULL DEFAULT 'planned',   -- planned | applied | cancelled
    planned_at    TEXT NOT NULL DEFAULT (datetime('now')),
    applied_at    TEXT,
    UNIQUE (service, tag, status)
);
CREATE INDEX IF NOT EXISTS idx_coexistence_planned_status ON coexistence_planned (status);
