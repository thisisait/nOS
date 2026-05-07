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
