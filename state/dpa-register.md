# nOS — GDPR Record of Processing Activities (Article 30)

> **Generated** by `tools/gdpr-dpa-register.py` from the per-plugin
> `gdpr:` blocks (Tier-1) and `apps/*.yml` manifests (Tier-2).
> **Do not edit by hand** — change the source `gdpr:` block and
> regenerate. Pinned by `tests/anatomy/test_gdpr_register_coverage.py`.
>
> This is the controller-side Record of Processing Activities a DPO
> reviews under GDPR Art. 30(1). Every service is self-hosted on the
> operator's own host; absent a declared processor (see below), there
> is no third-party data processor and no transfer outside the EU.

## Summary

- **Processing activities:** 68 (64 core services, 4 Tier-2 apps)
- **Legal basis (Art. 6(1)):** contract (5), legitimate_interests (63)
- **Transfers outside the EU:** 0 activities
- **Activities engaging a third-party processor:** 0
- ⚠️ **31 activities** carry an auto-generated purpose (plugin `gdpr.purpose` not yet authored) — flagged with † below.

## Transfers & processors (audit-sensitive subset)

None. Every processing activity is fully EU-resident and self-hosted with no third-party processor.

## Security measures (Art. 32 — platform baseline)

Inherited by every activity unless its `gdpr.security_measures`
overrides them. Authoritative prose: `docs/security-baseline.md`.

- TLS in transit (Traefik edge; wildcard cert)
- Authentik SSO + RBAC tier access control
- Secrets held in Infisical / launchd env, never plaintext at rest
- Disk encryption at rest is operator-provisioned (FileVault / LUKS)
- Self-hosted: no third-party data processor unless declared below

## Processing records

### infra stack

#### Authentik — `svc_authentik` †
- **Purpose:** Operation of the Authentik service within the nOS self-hosted platform; processing limited to what the service requires to function for authenticated users.
- **Legal basis (Art. 6):** `contract`
- **Data subjects:** `operators`, `end_users`, `automated_systems`
- **Data categories:** `authentication_credentials`, `identity_metadata`, `session_tokens`, `audit_log_entries`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** indefinite (lifecycle-managed; deletion via DSAR)
- **Storage:** 'infra' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Bluesky Pds — `svc_bluesky-pds` †
- **Purpose:** Operation of the Bluesky Pds service within the nOS self-hosted platform; processing limited to what the service requires to function for authenticated users.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`, `end_users`
- **Data categories:** `at_protocol_identities`, `social_repository_content`, `object_storage_blobs`, `account_credentials`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** indefinite (lifecycle-managed; deletion via DSAR)
- **Storage:** 'infra' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Infisical — `svc_infisical`
- **Purpose:** Hosts the operator's central secrets vault (Infisical CE). Stores
encrypted secrets, project metadata, audit logs, and OIDC session links.
Vault values are envelope-encrypted at rest.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`
- **Data categories:** `encrypted_secrets`, `audit_logs`, `oauth_session_data`, `email`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** indefinite (lifecycle-managed; deletion via DSAR)
- **Storage:** 'infra' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Mariadb — `svc_mariadb` †
- **Purpose:** Operation of the Mariadb service within the nOS self-hosted platform; processing limited to what the service requires to function for authenticated users.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`, `end_users`
- **Data categories:** `application_user_data`, `audit_logs`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** indefinite (lifecycle-managed; deletion via DSAR)
- **Storage:** 'infra' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Portainer — `svc_portainer` †
- **Purpose:** Operation of the Portainer service within the nOS self-hosted platform; processing limited to what the service requires to function for authenticated users.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`
- **Data categories:** `admin_credentials`, `oauth_session_data`, `audit_logs`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 365 days (~1y)
- **Storage:** 'infra' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Postgresql — `svc_postgresql` †
- **Purpose:** Operation of the Postgresql service within the nOS self-hosted platform; processing limited to what the service requires to function for authenticated users.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`, `end_users`
- **Data categories:** `application_user_data`, `audit_logs`, `oauth_session_data`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** indefinite (lifecycle-managed; deletion via DSAR)
- **Storage:** 'infra' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Redis — `svc_redis` †
- **Purpose:** Operation of the Redis service within the nOS self-hosted platform; processing limited to what the service requires to function for authenticated users.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`, `end_users`
- **Data categories:** `cache_data`, `oauth_session_data`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 1 days
- **Storage:** 'infra' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Smtp Stalwart — `svc_smtp-stalwart` †
- **Purpose:** Operation of the Smtp Stalwart service within the nOS self-hosted platform; processing limited to what the service requires to function for authenticated users.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`, `mailbox_owners`, `external_correspondents`
- **Data categories:** `mailbox_contents`, `smtp_envelope_metadata`, `mailbox_credentials`, `delivery_logs`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 365 days (~1y)
- **Storage:** 'infra' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Traefik — `svc_traefik` †
- **Purpose:** Operation of the Traefik service within the nOS self-hosted platform; processing limited to what the service requires to function for authenticated users.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`, `end_users`
- **Data categories:** `request_metadata`, `client_ip_addresses`, `user_agent_strings`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 30 days
- **Storage:** 'infra' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

### observability stack

#### Alloy — `svc_alloy` †
- **Purpose:** Operation of the Alloy service within the nOS self-hosted platform; processing limited to what the service requires to function for authenticated users.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`, `end_users`
- **Data categories:** `infrastructure_metrics`, `log_lines_in_transit`, `trace_spans_in_transit`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 1 days
- **Storage:** 'observability' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Grafana — `svc_grafana` †
- **Purpose:** Operation of the Grafana service within the nOS self-hosted platform; processing limited to what the service requires to function for authenticated users.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operator`, `admins`
- **Data categories:** `usage_metrics`, `dashboard_view_logs`, `oauth_session_data`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 365 days (~1y)
- **Storage:** 'observability' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Influxdb — `svc_influxdb`
- **Purpose:** Operator-hosted time-series database (admin UI proxy-gated). Forward-auth gate ensures only
Authentik-authenticated principals reach the service.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`
- **Data categories:** `timeseries_metrics`, `bucket_metadata`, `oauth_session_data`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 365 days (~1y)
- **Storage:** 'observability' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Loki — `svc_loki` †
- **Purpose:** Operation of the Loki service within the nOS self-hosted platform; processing limited to what the service requires to function for authenticated users.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`, `end_users`
- **Data categories:** `log_lines`, `hostname_labels`, `request_metadata`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 30 days
- **Storage:** 'observability' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Prometheus — `svc_prometheus` †
- **Purpose:** Operation of the Prometheus service within the nOS self-hosted platform; processing limited to what the service requires to function for authenticated users.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`
- **Data categories:** `infrastructure_metrics`, `hostname_labels`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 30 days
- **Storage:** 'observability' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Tempo — `svc_tempo` †
- **Purpose:** Operation of the Tempo service within the nOS self-hosted platform; processing limited to what the service requires to function for authenticated users.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`, `end_users`
- **Data categories:** `trace_spans`, `request_metadata`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 14 days
- **Storage:** 'observability' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

### iiab stack

#### Calibre Web — `svc_calibre-web`
- **Purpose:** Operator-hosted ebook library web reader (Calibre frontend). Forward-auth gate ensures only
Authentik-authenticated principals reach the service.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`, `end_users`
- **Data categories:** `ebook_metadata`, `reading_progress`, `oauth_session_data`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 365 days (~1y)
- **Storage:** 'iiab' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Homeassistant — `svc_homeassistant`
- **Purpose:** Hosts the operator's Home Assistant smart-home hub. Stores device
states, automations, sensor history, user accounts, and OIDC
session data. Telemetry from physical IoT devices stays on-host.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`, `household_members`
- **Data categories:** `device_telemetry`, `sensor_history`, `automation_definitions`, `user_accounts`, `oauth_session_data`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 365 days (~1y)
- **Storage:** 'iiab' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Kiwix — `svc_kiwix`
- **Purpose:** Operator-hosted offline content reader (Wikipedia, Gutenberg, ZIM archives). Forward-auth gate ensures only
Authentik-authenticated principals reach the service.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`, `end_users`
- **Data categories:** `zim_access_logs`, `oauth_session_data`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 90 days
- **Storage:** 'iiab' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Mailpit — `svc_mailpit`
- **Purpose:** Operator-hosted SMTP testing sink + web UI for dev mail capture. Forward-auth gate ensures only
Authentik-authenticated principals reach the service.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`
- **Data categories:** `captured_email_bodies`, `smtp_envelope_metadata`, `oauth_session_data`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 7 days
- **Storage:** 'iiab' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Mcp Gateway — `svc_mcp-gateway` †
- **Purpose:** Operation of the Mcp Gateway service within the nOS self-hosted platform; processing limited to what the service requires to function for authenticated users.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`, `automated_systems`
- **Data categories:** `mcp_request_metadata`, `filesystem_access_logs`, `git_repo_access_logs`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 30 days
- **Storage:** 'iiab' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Miniflux — `svc_miniflux`
- **Purpose:** Hosts the operator's RSS aggregator. Stores feed subscriptions,
read/unread state, starred items, and the OIDC session link.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`, `end_users`
- **Data categories:** `feed_subscriptions`, `read_state`, `oauth_session_data`, `email`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 365 days (~1y)
- **Storage:** 'iiab' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### N8N — `svc_n8n`
- **Purpose:** Hosts the operator's n8n workflow automation platform. Stores
workflow definitions, execution history, credentials, and OIDC
session data. Workflows may process third-party data subjects'
information depending on the operator's automations.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`, `end_users`
- **Data categories:** `workflow_definitions`, `execution_history`, `encrypted_credentials`, `oauth_session_data`, `email`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 365 days (~1y)
- **Storage:** 'iiab' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Nextcloud — `svc_nextcloud`
- **Purpose:** Hosts the operator's Nextcloud collaboration suite. Stores files,
contacts, calendars, talk messages, user accounts, and OIDC session
data. May process end-user uploads.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`, `end_users`
- **Data categories:** `file_storage`, `contacts`, `calendars`, `chat_messages`, `user_accounts`, `oauth_session_data`, `email`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 365 days (~1y)
- **Storage:** 'iiab' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Nodered — `svc_nodered`
- **Purpose:** Operator-hosted flow-based programming for IoT and integration. Forward-auth gate ensures only
Authentik-authenticated principals reach the service.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`
- **Data categories:** `flow_definitions`, `credential_nodes`, `oauth_session_data`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 365 days (~1y)
- **Storage:** 'iiab' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Ntfy — `svc_ntfy`
- **Purpose:** Operator-hosted pub/sub HTTP push notifications server. Forward-auth gate ensures only
Authentik-authenticated principals reach the service.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`, `end_users`
- **Data categories:** `topic_messages`, `subscriber_endpoints`, `oauth_session_data`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 30 days
- **Storage:** 'iiab' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Offline Maps — `svc_offline-maps` †
- **Purpose:** Operation of the Offline Maps service within the nOS self-hosted platform; processing limited to what the service requires to function for authenticated users.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`, `end_users`
- **Data categories:** `tile_request_logs`, `hostname_labels`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 30 days
- **Storage:** 'iiab' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Open Webui — `svc_open-webui`
- **Purpose:** Hosts the operator's Open WebUI chat front-end for Ollama. Stores
chat conversations, prompt history, model preferences, and OIDC
session data.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`, `end_users`
- **Data categories:** `chat_messages`, `prompt_history`, `user_accounts`, `oauth_session_data`, `email`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 365 days (~1y)
- **Storage:** 'iiab' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Puter — `svc_puter`
- **Purpose:** Operator-hosted cloud-OS web desktop (multi-user, AI, iframe apps). Forward-auth gate ensures only
Authentik-authenticated principals reach the service.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`, `end_users`
- **Data categories:** `user_files`, `app_state`, `oauth_session_data`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** indefinite (lifecycle-managed; deletion via DSAR)
- **Storage:** 'iiab' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Rustfs — `svc_rustfs` †
- **Purpose:** Operation of the Rustfs service within the nOS self-hosted platform; processing limited to what the service requires to function for authenticated users.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`
- **Data categories:** `object_storage_blobs`, `access_logs`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 90 days
- **Storage:** 'iiab' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Snappymail — `svc_snappymail`
- **Purpose:** Operator-hosted webmail client (SnappyMail). Forward-auth gate ensures only
Authentik-authenticated principals reach the webmail UI. IMAP/SMTP credentials
are stored in SnappyMail's data directory and used to connect to the upstream
mail server (Stalwart).
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`, `end_users`
- **Data categories:** `imap_smtp_credentials`, `webmail_session_data`, `oauth_session_data`, `email_cache_metadata`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 365 days (~1y)
- **Storage:** 'iiab' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Uptime Kuma — `svc_uptime-kuma`
- **Purpose:** Operator-hosted service uptime monitoring dashboard. Forward-auth gate ensures only
Authentik-authenticated principals reach the service.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`
- **Data categories:** `monitor_status`, `uptime_history`, `oauth_session_data`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 365 days (~1y)
- **Storage:** 'iiab' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Vaultwarden — `svc_vaultwarden`
- **Purpose:** Hosts the operator's (and optionally family / team members') Bitwarden
vault — encrypted credentials, TOTP seeds, secure notes, encrypted file
attachments. Master password is operator-owned and never reaches the
server in clear; Vaultwarden stores only the master-password-encrypted
blob plus the OIDC link (when Authentik SSO is enabled).
- **Legal basis (Art. 6):** `contract`
- **Data subjects:** `operators`, `end_users`
- **Data categories:** `encrypted_credentials`, `master_password_hash`, `encrypted_attachments`, `oauth_session_data`, `email`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** indefinite (lifecycle-managed; deletion via DSAR)
- **Storage:** 'iiab' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Watchtower — `svc_watchtower` †
- **Purpose:** Operation of the Watchtower service within the nOS self-hosted platform; processing limited to what the service requires to function for authenticated users.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`
- **Data categories:** `container_metadata`, `update_event_logs`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 30 days
- **Storage:** 'iiab' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Wordpress — `svc_wordpress`
- **Purpose:** Hosts the operator's WordPress site. Stores posts, pages, comments,
user accounts, and OIDC session data. Public-facing content may be
reachable to anonymous visitors (legitimate interests basis).
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`, `end_users`, `anonymous_visitors`
- **Data categories:** `blog_content`, `comments`, `user_accounts`, `oauth_session_data`, `email`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 365 days (~1y)
- **Storage:** 'iiab' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

### apps stack

#### Documenso — `app_documenso`
- **Purpose:** Allow the operator to send PDFs for legally-binding e-signature and
retain the signed copy + signature audit log. Required to fulfil
contracts with counter-parties who agree to electronic execution.
- **Legal basis (Art. 6):** `contract`
- **Data subjects:** `end_users`, `operators`
- **Data categories:** `name`, `email`, `ip_address`, `signature_image`, `document_content`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 365 days (~1y)
- **Storage:** 'apps' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Qdrant — `app_qdrant`
- **Purpose:** Hosts vector embeddings + payload metadata for the nOS agentic platform:
semantic search over agent outputs, system metadata, and cybersec
intelligence. Embeddings are derived from text the operator chose to
process (audit logs, CVE descriptions, system facts) — Qdrant itself
does not collect data; it persists what Bone uploads.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`
- **Data categories:** `agent_run_metadata`, `system_facts`, `cybersec_metadata`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 365 days (~1y)
- **Storage:** 'apps' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Roundcube — `app_roundcube`
- **Purpose:** Web frontend over the operator's IMAP/SMTP mail server. Roundcube
itself stores only UI prefs, address book entries, and a short-term
cache of message metadata for performance — message bodies live on
the IMAP server (which has its own Article 30 entry).
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`, `end_users`
- **Data categories:** `email_metadata`, `address_book_entries`, `ui_preferences`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 365 days (~1y)
- **Storage:** 'apps' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Twofauth — `app_twofauth`
- **Purpose:** Hosts the operator's TOTP / HOTP authenticator secrets so they can be
reached from any device on the LAN without locking the operator into
a single phone. Replaces a hardware authenticator + paper backup. No
third-party user data — the operator is the only data subject.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`
- **Data categories:** `credentials`, `authentication_metadata`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** indefinite (lifecycle-managed; deletion via DSAR)
- **Storage:** 'apps' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Qdrant — `svc_qdrant` †
- **Purpose:** Operation of the Qdrant service within the nOS self-hosted platform; processing limited to what the service requires to function for authenticated users.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`, `automated_systems`
- **Data categories:** `agent_prompt_context`, `advisory_text`, `vector_metadata`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 365 days (~1y)
- **Storage:** 'apps' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

### devops stack

#### Code Server — `svc_code-server`
- **Purpose:** Operator-hosted VS Code in the browser (LinuxServer.io image). Forward-auth gate ensures only
Authentik-authenticated principals reach the service.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`
- **Data categories:** `workspace_files`, `git_credentials`, `oauth_session_data`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 365 days (~1y)
- **Storage:** 'devops' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Gitea — `svc_gitea` †
- **Purpose:** Operation of the Gitea service within the nOS self-hosted platform; processing limited to what the service requires to function for authenticated users.
- **Legal basis (Art. 6):** `contract`
- **Data subjects:** `operators`, `end_users`
- **Data categories:** `identity_metadata`, `authentication_credentials`, `source_code`, `audit_log_entries`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** indefinite (lifecycle-managed; deletion via DSAR)
- **Storage:** 'devops' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Gitlab — `svc_gitlab`
- **Purpose:** Hosts the operator's GitLab source-control + CI platform. Stores
repositories, issues, merge requests, CI artifacts, user accounts,
and OIDC session data.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`, `end_users`
- **Data categories:** `repository_content`, `issues_and_mrs`, `ci_artifacts`, `user_accounts`, `oauth_session_data`, `email`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 365 days (~1y)
- **Storage:** 'devops' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Paperclip — `svc_paperclip`
- **Purpose:** Operator-hosted multi-agent orchestration platform. Forward-auth gate ensures only
Authentik-authenticated principals reach the service.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`
- **Data categories:** `agent_runs`, `task_artifacts`, `oauth_session_data`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 365 days (~1y)
- **Storage:** 'devops' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Woodpecker — `svc_woodpecker` †
- **Purpose:** Operation of the Woodpecker service within the nOS self-hosted platform; processing limited to what the service requires to function for authenticated users.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operator`, `developers`
- **Data categories:** `ci_pipeline_logs`, `oauth_session_data`, `commit_author_metadata`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 90 days
- **Storage:** 'devops' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

### b2b stack

#### Bookstack — `svc_bookstack`
- **Purpose:** Hosts the operator's BookStack wiki. Stores pages, page revisions,
user accounts, and the OIDC session link.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`, `end_users`
- **Data categories:** `wiki_content`, `revision_history`, `user_accounts`, `oauth_session_data`, `email`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 365 days (~1y)
- **Storage:** 'b2b' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Erpnext — `svc_erpnext` †
- **Purpose:** Operation of the Erpnext service within the nOS self-hosted platform; processing limited to what the service requires to function for authenticated users.
- **Legal basis (Art. 6):** `contract`
- **Data subjects:** `operators`, `end_users`, `third_parties`
- **Data categories:** `identity_metadata`, `financial_records`, `hr_data`, `customer_data`, `audit_log_entries`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 2555 days (~7y)
- **Storage:** 'b2b' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Firefly — `svc_firefly`
- **Purpose:** Operator-hosted personal finance manager. Forward-auth gate ensures only
Authentik-authenticated principals reach the service.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`, `end_users`
- **Data categories:** `transaction_history`, `account_balances`, `tags`, `oauth_session_data`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** indefinite (lifecycle-managed; deletion via DSAR)
- **Storage:** 'b2b' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Freescout — `svc_freescout`
- **Purpose:** Hosts the operator's FreeScout helpdesk system. Stores customer
conversations, ticket history, internal notes, agent accounts, and
OIDC session data. Customer email content is processed for support
purposes (legitimate interests basis, contractual where the customer
has an active service agreement).
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`, `support_agents`, `end_users`
- **Data categories:** `support_conversations`, `ticket_metadata`, `customer_emails`, `internal_notes`, `user_accounts`, `oauth_session_data`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 1095 days (~3y)
- **Storage:** 'b2b' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Hedgedoc — `svc_hedgedoc`
- **Purpose:** Hosts the operator's HedgeDoc collaborative markdown notes. Stores
documents, edit history, and OIDC session links.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`, `end_users`
- **Data categories:** `document_content`, `edit_history`, `oauth_session_data`, `email`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 365 days (~1y)
- **Storage:** 'b2b' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Onlyoffice — `svc_onlyoffice`
- **Purpose:** Operator-hosted collaborative office editor backend. Forward-auth gate ensures only
Authentik-authenticated principals reach the service.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`, `end_users`
- **Data categories:** `document_edits`, `collaboration_sessions`, `oauth_session_data`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 365 days (~1y)
- **Storage:** 'b2b' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Outline — `svc_outline`
- **Purpose:** Hosts the operator's Outline collaborative wiki. Stores documents,
document revisions, comments, user accounts, and OIDC session data.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`, `end_users`
- **Data categories:** `wiki_content`, `revision_history`, `comments`, `user_accounts`, `oauth_session_data`, `email`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 365 days (~1y)
- **Storage:** 'b2b' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

### voip stack

#### Freepbx — `svc_freepbx` †
- **Purpose:** Operation of the Freepbx service within the nOS self-hosted platform; processing limited to what the service requires to function for authenticated users.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`, `extension_users`, `external_callers`
- **Data categories:** `call_metadata`, `voicemail_recordings`, `extension_credentials`, `dialplan_state`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 90 days
- **Storage:** 'voip' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

### engineering stack

#### Qgis Server — `svc_qgis-server` †
- **Purpose:** Operation of the Qgis Server service within the nOS self-hosted platform; processing limited to what the service requires to function for authenticated users.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`, `automated_systems`
- **Data categories:** `ogc_request_logs`, `hostname_labels`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 30 days
- **Storage:** 'engineering' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

### data stack

#### Superset — `svc_superset`
- **Purpose:** Hosts the operator's BI dashboards (Apache Superset). Stores dataset
metadata, dashboard definitions, query history, and user sessions.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`
- **Data categories:** `dashboard_definitions`, `query_history`, `user_accounts`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 365 days (~1y)
- **Storage:** 'data' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

### host stack

#### Wing — `svc_wing`
- **Purpose:** Operator-hosted security-research dashboard (FrankenPHP host daemon). Forward-auth gate ensures only
Authentik-authenticated principals reach the service.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`
- **Data categories:** `systems_inventory`, `remediation_items`, `audit_events`, `oauth_session_data`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** indefinite (lifecycle-managed; deletion via DSAR)
- **Storage:** 'host' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

### host / non-stack

#### Alloy Docker Metrics — `svc_alloy-docker-metrics` †
- **Purpose:** Operation of the Alloy Docker Metrics service within the nOS self-hosted platform; processing limited to what the service requires to function for authenticated users.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`, `end_users`
- **Data categories:** `infrastructure_metrics`, `container_logs`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 7 days
- **Storage:** host service (non-Docker / launchd)
- **Security measures:** platform baseline (see above)

#### Alloy Host Metrics — `svc_alloy-host-metrics` †
- **Purpose:** Operation of the Alloy Host Metrics service within the nOS self-hosted platform; processing limited to what the service requires to function for authenticated users.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`
- **Data categories:** `infrastructure_metrics`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 30 days
- **Storage:** host service (non-Docker / launchd)
- **Security measures:** platform baseline (see above)

#### Alloy Syslog — `svc_alloy-syslog` †
- **Purpose:** Operation of the Alloy Syslog service within the nOS self-hosted platform; processing limited to what the service requires to function for authenticated users.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`, `end_users`
- **Data categories:** `operational_logs`, `audit_trail_logs`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 14 days
- **Storage:** host service (non-Docker / launchd)
- **Security measures:** platform baseline (see above)

#### Gitleaks — `svc_gitleaks`
- **Purpose:** Secret detection in operator-managed source repositories (nOS repo)
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`
- **Data categories:** `source_code_metadata`, `partial_credentials`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 365 days (~1y)
- **Storage:** host service (non-Docker / launchd)
- **Security measures:** platform baseline (see above)

#### Grafana Loki — `svc_grafana-loki` †
- **Purpose:** Operation of the Grafana Loki service within the nOS self-hosted platform; processing limited to what the service requires to function for authenticated users.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`
- **Data categories:** `log_query_metadata`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** transient (not persisted)
- **Storage:** host service (non-Docker / launchd)
- **Security measures:** platform baseline (see above)

#### Grafana Prometheus — `svc_grafana-prometheus` †
- **Purpose:** Operation of the Grafana Prometheus service within the nOS self-hosted platform; processing limited to what the service requires to function for authenticated users.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`
- **Data categories:** `infrastructure_metrics`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 30 days
- **Storage:** host service (non-Docker / launchd)
- **Security measures:** platform baseline (see above)

#### Grafana Tempo — `svc_grafana-tempo` †
- **Purpose:** Operation of the Grafana Tempo service within the nOS self-hosted platform; processing limited to what the service requires to function for authenticated users.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`
- **Data categories:** `trace_spans`, `request_metadata`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 14 days
- **Storage:** host service (non-Docker / launchd)
- **Security measures:** platform baseline (see above)

#### Grafana Wing — `svc_grafana-wing` †
- **Purpose:** Operation of the Grafana Wing service within the nOS self-hosted platform; processing limited to what the service requires to function for authenticated users.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`
- **Data categories:** `playbook_event_metadata`, `agent_session_telemetry`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** transient (not persisted)
- **Storage:** host service (non-Docker / launchd)
- **Security measures:** platform baseline (see above)

#### Jellyfin — `svc_jellyfin`
- **Purpose:** Hosts the operator's media library (movies / TV / music). Stores user
accounts (per-family-member profiles), watch history, and library
metadata.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`, `end_users`
- **Data categories:** `user_accounts`, `watch_history`, `media_metadata`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 365 days (~1y)
- **Storage:** host service (non-Docker / launchd)
- **Security measures:** platform baseline (see above)

#### Metabase — `svc_metabase`
- **Purpose:** Hosts the operator's Metabase BI dashboards. Stores question /
dashboard / collection metadata, query history, user accounts.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`
- **Data categories:** `dashboard_definitions`, `query_history`, `user_accounts`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 365 days (~1y)
- **Storage:** host service (non-Docker / launchd)
- **Security measures:** platform baseline (see above)

#### Openclaw — `svc_openclaw`
- **Purpose:** OpenClaw is the operator's local LLM gateway. It receives prompts from
the operator (via Hermes / Wing / direct curl), forwards them to Ollama
(running on the same host with MLX backend), and returns generated
text. No prompts or completions persist beyond the active request
unless the caller explicitly POSTs to Wing /events with source=agent:*
(in which case A10 actor_id audit applies).
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`
- **Data categories:** `operator_prompts`, `agent_run_metadata`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** transient (not persisted)
- **Storage:** host service (non-Docker / launchd)
- **Security measures:** platform baseline (see above)

#### Pulse — `svc_pulse` †
- **Purpose:** Operation of the Pulse service within the nOS self-hosted platform; processing limited to what the service requires to function for authenticated users.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`
- **Data categories:** `aggregated_job_metadata`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** indefinite (lifecycle-managed; deletion via DSAR)
- **Storage:** host service (non-Docker / launchd)
- **Security measures:** platform baseline (see above)

#### Spacetimedb — `svc_spacetimedb`
- **Purpose:** Hosts the operator's SpacetimeDB realtime DB modules. Stores user-defined
tables, table rows, and the cryptographic identity (ctx.sender.identity)
of every module caller. Module-level data subject is operator-defined.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operator`, `module_callers`
- **Data categories:** `module_state`, `operator_identity`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 365 days (~1y)
- **Storage:** host service (non-Docker / launchd)
- **Security measures:** platform baseline (see above)
