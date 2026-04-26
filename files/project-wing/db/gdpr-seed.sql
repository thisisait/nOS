-- GDPR Article 30 register — default seed for nOS deployments.
-- Loaded by bin/init-db.php after schema-extensions.sql.
-- Operators add their own processing activities by INSERTing into
-- gdpr_processing through Wing's /gdpr UI or directly via SQLite.
--
-- All rows use INSERT OR IGNORE so re-running init-db.php doesn't trample
-- operator edits to seeded entries. To force-refresh a seeded row, DELETE
-- it first, then re-run.

INSERT OR IGNORE INTO gdpr_processing (
    id, name, purpose, legal_basis,
    data_categories, data_subjects,
    retention_days, storage_location,
    transfers_outside_eu, processors, security_measures, notes
) VALUES
(
    'auth',
    'Authentication and SSO (Authentik)',
    'Verify identity for access to nOS services. Required for the contract / legitimate operation of the system.',
    'contract',
    '["username","email","password_hash","group_membership","login_timestamps","ip_address"]',
    '["operators","end-users"]',
    365,
    'PostgreSQL inside the infra Docker stack on the host',
    0,
    '[]',
    '["Argon2 password hashing","TLS in transit","row-level encryption at rest via volume encryption","audit log via auditd"]',
    'Authentik is the IAM source of truth. Account deletion via the Authentik admin UI cascades to all OIDC apps that bind to the same user model.'
),
(
    'telemetry',
    'Wing telemetry (Ansible run events)',
    'Observability of operational changes. Helps operator debug failed runs and audit who changed what.',
    'legitimate-interest',
    '["hostname","username","task_name","change_summary","timestamp","run_id"]',
    '["operators"]',
    180,
    'SQLite database at ~/wing/app/data/wing.db (host-local)',
    0,
    '[]',
    '["HMAC-SHA256 on the ingestion endpoint","loopback-only network access","SQLite file owned by uid 10082 with 0640 permissions"]',
    'Telemetry contains operator usernames and task descriptions but no end-user data. Retention auto-trimmed by the events_retention_cron (see pazny.wing/tasks/post.yml) — adjust via wing_telemetry_retention_days.'
),
(
    'tenant-vault',
    'Personal password vault (Vaultwarden)',
    'Self-service password storage for end-users. Independent of the operator-managed vault (Infisical).',
    'consent',
    '["passwords","secret_notes","TOTP_seeds","attachments_user_supplied"]',
    '["end-users"]',
    NULL,
    'Encrypted SQLite database in the Vaultwarden container volume',
    0,
    '[]',
    '["End-to-end encryption — Vaultwarden cannot decrypt vault contents","TLS in transit","operator cannot read tenant vaults without the tenant''s password"]',
    'Retention is "indefinite" because vault contents are owned by the end-user. The user can delete their account via the Vaultwarden UI which purges the vault.'
),
(
    'collab-docs',
    'Collaborative documents (Outline / HedgeDoc / BookStack / Nextcloud)',
    'Hosted document editing for operators and tenants.',
    'consent',
    '["documents","comments","author_metadata","attachments"]',
    '["operators","end-users"]',
    NULL,
    'Postgres + object storage in the b2b / iiab Docker stacks',
    0,
    '[]',
    '["TLS in transit","Authentik SSO authentication","RBAC via Authentik tier groups","backups encrypted via restic"]',
    'Retention follows operator-defined document lifecycle. Deletion through the app UI cascades to backups within 30 days (next restic forget run).'
),
(
    'project-knowledge',
    'AT Protocol identity bridge (Bluesky PDS)',
    'Bridge Authentik identities to AT Protocol handles for federated social use.',
    'consent',
    '["did","handle","signing_keys"]',
    '["end-users"]',
    NULL,
    'PostgreSQL in the infra stack',
    0,
    '[]',
    '["TLS in transit","keys held in encrypted Postgres column","Authentik bridge requires explicit consent at first login"]',
    'Federation is not enabled by default (requires public DNS). Tenants who never log in have no record created. Account deletion in Authentik triggers tombstoning in the PDS within 24h.'
),
(
    'support-tickets',
    'Customer support tickets (FreeScout)',
    'Track support communications with end-users.',
    'contract',
    '["email_address","name","ticket_content","attachments_uploaded"]',
    '["end-users"]',
    1095,
    'MySQL inside b2b stack',
    0,
    '[]',
    '["TLS in transit","Authentik SSO for operator access","retention enforced by daily prune cron"]',
    '3-year retention reflects warranty / consumer-rights statute of limitations. Configurable via freescout_retention_days.'
),
(
    'observability',
    'Operational metrics + logs (LGTM stack)',
    'Capacity planning, incident response, compliance audit trail.',
    'legitimate-interest',
    '["host_metrics","container_metrics","application_logs","trace_spans"]',
    '["operators"]',
    90,
    'Prometheus TSDB + Loki + Tempo on host disk',
    0,
    '[]',
    '["No PII collected by default — log scrubbing rules in tasks/observability.yml","TLS in transit","RBAC via Authentik for Grafana access"]',
    'Logs are scrubbed of email addresses and IPs by default in the Loki ingestion pipeline. Operators that need PII in logs (e.g. for fraud investigation) must explicitly toggle wing_log_scrub_pii=false and document the legal basis.'
),
(
    'backups',
    'System and data backups (restic + RustFS)',
    'Disaster recovery and accidental-deletion recovery.',
    'legitimate-interest',
    '["all_above_categories_in_encrypted_form"]',
    '["operators","end-users"]',
    365,
    'RustFS S3-compatible object storage (host-local by default; offsite optional)',
    0,
    '[]',
    '["restic repository encryption (XChaCha20-Poly1305)","passphrase held only in Infisical","integrity checks via restic check"]',
    'Backups inherit the legal basis of the underlying data. End-user erasure requests propagate to backups via restic forget on the next scheduled run (within 24h).'
);
