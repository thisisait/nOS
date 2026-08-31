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

## Controller & DPO (Art. 30(1)(a))

- **Controller:** _(unset — export GDPR_CONTROLLER_NAME)_
- **DPO / contact point:** _(unset — export GDPR_DPO_NAME)_
- **DPO contact:** _(unset — export GDPR_DPO_CONTACT)_

_Standalone step: export the three `GDPR_*` env vars and re-run `tools/gdpr-dpa-register.py` to populate (not set by any playbook profile yet)._

## Summary

- **Processing activities:** 95 (77 core services, 4 Tier-2 apps)
- **Legal basis (Art. 6(1)):** contract (5), legal_obligation (1), legitimate_interests (89)
- **Transfers outside the EU:** 11 activities
- **Activities engaging a third-party processor:** 14

## Transfers & processors (audit-sensitive subset)

| Service | Outside EU? | Processors |
|---|---|---|
| conductor (`agent_conductor`) | **Yes** | **MiniMax** (unverified — international endpoint api.minimax.io; entity and seat not established) — LLM inference via the Anthropic-compatible endpoint (SDK adapter, tool loop driven by AgentKit). The bound backend for this ceremony. · safeguard: None established. Recorded as UNVERIFIED rather than asserted; the binding gate refuses a backend this record does not name, so this entry is what permits the routing and must not be written as a claim it cannot support.; **Anthropic, PBC** (US) — LLM inference when this ceremony is driven on the claude-CLI path rather than the bound backend (--print) · safeguard: None claimed. Assess SCCs / Art. 46 before this is relied on. |
| curator (`agent_curator`) | **Yes** | **MiniMax** (unverified — international endpoint api.minimax.io; entity and seat not established) — LLM inference via the Anthropic-compatible endpoint (SDK adapter, tool loop driven by AgentKit). The bound backend for this ceremony. · safeguard: None established. Recorded as UNVERIFIED rather than asserted; the binding gate refuses a backend this record does not name, so this entry is what permits the routing and must not be written as a claim it cannot support.; **Anthropic, PBC** (US) — LLM inference when this ceremony is driven on the claude-CLI path rather than the bound backend (--print) · safeguard: None claimed. Assess SCCs / Art. 46 before this is relied on. |
| jeff (`agent_jeff`) | No | **on-device (operator's own hardware)** (CZ — this host) — LLM inference on this host via ollama's OpenAI-compatible surface on loopback. No third party sees the prompt, so there is no processor in the Article-28 sense; this entry says so rather than leaving the field blank. · safeguard: Not applicable. No transfer occurs, which is stronger than any safeguard could describe. |
| jeff-cloud (`agent_jeff-cloud`) | **Yes** | **MiniMax** (unverified — international endpoint api.minimax.io; entity and seat not established) — LLM inference via the Anthropic-compatible endpoint (SDK adapter, tool loop driven by AgentKit). The bound backend for this agent. · safeguard: None established. Recorded as UNVERIFIED rather than asserted; the binding gate refuses a backend this record does not name, so this entry is what permits the routing and must not be written as a claim it cannot support. |
| librarian (`agent_librarian`) | **Yes** | **Anthropic, PBC** (US) — LLM inference for the ceremony's reasoning (claude CLI, --print) · safeguard: None claimed. Assess SCCs / Art. 46 before this is relied on.; **MiniMax** (unverified — international endpoint api.minimax.io; entity and seat not established) — LLM inference via the Anthropic-compatible endpoint (SDK adapter, tool loop driven by AgentKit) · safeguard: None claimed, and none assessed. No SCCs, adequacy finding or derogation has been identified for this transfer. |
| migration-author (`agent_migration-author`) | **Yes** | **Anthropic, PBC** (US) — LLM inference for the ceremony's reasoning (claude CLI, --print) · safeguard: None claimed. Assess SCCs / Art. 46 before this is relied on. |
| ops-extract (`agent_ops-extract`) | No | **on-device (operator's own hardware)** (CZ — this host) — LLM inference on this host via ollama's OpenAI-compatible surface on loopback. There is no third party: the prompt does not leave the machine, so there is no processor in the Article-28 sense and this entry exists to say so rather than leave the field blank. · safeguard: Not applicable. No transfer occurs, which is a stronger position than any safeguard could describe. |
| ops-extract-cloud (`agent_ops-extract-cloud`) | **Yes** | **MiniMax** (unverified — international endpoint api.minimax.io; entity and seat not established) — LLM inference via the Anthropic-compatible endpoint (SDK adapter, single call, no tool loop) · safeguard: None claimed, and none assessed. No SCCs, adequacy finding or derogation has been identified for this transfer. |
| ops-triage (`agent_ops-triage`) | No | **on-device (operator's own hardware)** (CZ — this host) — LLM inference on this host via ollama's OpenAI-compatible surface on loopback. No third party: the prompt does not leave the machine, so there is no processor in the Article-28 sense and this entry says so rather than leaving the field blank. · safeguard: Not applicable. No transfer occurs. |
| ops-triage-cloud (`agent_ops-triage-cloud`) | **Yes** | **MiniMax** (unverified — international endpoint api.minimax.io; entity and seat not established) — LLM inference via the Anthropic-compatible endpoint (SDK adapter, single call, no tool loop) · safeguard: None claimed, and none assessed. No SCCs, adequacy finding or derogation has been identified for this transfer. |
| proposer (`agent_proposer`) | **Yes** | **MiniMax** (unverified — international endpoint api.minimax.io; entity and seat not established) — LLM inference via the Anthropic-compatible endpoint (SDK adapter, tool loop driven by AgentKit) · safeguard: None claimed, and none assessed. No SCCs, adequacy finding or derogation has been identified for this transfer. |
| surveyor (`agent_surveyor`) | **Yes** | **MiniMax** (unverified — international endpoint api.minimax.io; entity and seat not established) — LLM inference via the Anthropic-compatible endpoint (SDK adapter, tool loop driven by AgentKit). The bound backend for this ceremony. · safeguard: None established. Recorded as UNVERIFIED rather than asserted; the binding gate refuses a backend this record does not name, so this entry is what permits the routing and must not be written as a claim it cannot support.; **Anthropic, PBC** (US) — LLM inference when this ceremony is driven on the claude-CLI path rather than the bound backend (--print) · safeguard: None claimed. Assess SCCs / Art. 46 before this is relied on. |
| upgrade-architect (`agent_upgrade-architect`) | **Yes** | **Anthropic, PBC** (US) — LLM inference for the ceremony's reasoning (claude CLI, --print) · safeguard: None claimed. Assess SCCs / Art. 46 before this is relied on. |
| Loop (`svc_loop`) | **Yes** | `Anthropic (US) — claude CLI backend, authoring proposals when the propose job runs` |

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

#### Authentik — `svc_authentik`
- **Purpose:** Authentik is the platform identity provider and SSO authority. It
processes user identity metadata (username, display name, email),
authentication credentials (password hashes), session and API tokens, and
auth audit events (sign-in, group/RBAC changes) in order to authenticate
users and authorise their access to every nOS service. Authentication is
a precondition of providing the service to the user, so the legal basis is
contract (Art. 6(1)(b)). Subjects include human operators and tenant
end-users as well as automated agent clients (Bone, Pulse, conductor).
- **Legal basis (Art. 6):** `contract`
- **Data subjects:** `operators`; `end_users`; `automated_systems`
- **Data categories:** `authentication_credentials`; `identity_metadata`; `session_tokens`; `audit_log_entries`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** indefinite (lifecycle-managed; deletion via DSAR)
- **Storage:** 'infra' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Bluesky Pds — `svc_bluesky-pds`
- **Purpose:** The Bluesky Personal Data Server hosts AT Protocol identities (DID +
handle records), each user's social repository (posts, likes, follows and
other records), uploaded media blobs, and PDS-local account credentials
(password hashes for the admin and bridged tenant accounts). It processes
this to provide a self-hosted decentralised-social-identity service to
tenants who are bridged an @user.bsky.<tld> account (legitimate interest
in operating the social service, Art. 6(1)(f)). The repository lifecycle
is operator-managed; deletion is handled via the Art-17 erasure path.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`; `end_users`
- **Data categories:** `at_protocol_identities`; `social_repository_content`; `object_storage_blobs`; `account_credentials`
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
- **Data categories:** `encrypted_secrets`; `audit_logs`; `oauth_session_data`; `email`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** indefinite (lifecycle-managed; deletion via DSAR)
- **Storage:** 'infra' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Mariadb — `svc_mariadb`
- **Purpose:** MariaDB is the shared relational datastore for MySQL-family services. It
persists whatever the consuming services write — application user and
content rows plus their audit logs (e.g. WordPress, Nextcloud, FreeScout)
— so those services can function (legitimate interest in operating the
persistence layer, Art. 6(1)(f)). End-user PII present here is owned by the
consuming service; data lifetime and the precise processing purpose are
determined by that service, not by MariaDB itself.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`; `end_users`
- **Data categories:** `application_user_data`; `audit_logs`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** indefinite (lifecycle-managed; deletion via DSAR)
- **Storage:** 'infra' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Portainer — `svc_portainer`
- **Purpose:** Portainer is the operator-facing Docker management console. It processes
the admin password hash, Authentik OIDC session data, and its own limited
activity audit log, in order to let operators administer the container
estate (legitimate interest in service operation, Art. 6(1)(f)). The only
data subjects are operators; no tenant end-user data is processed.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`
- **Data categories:** `admin_credentials`; `oauth_session_data`; `audit_logs`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 365 days (~1y)
- **Storage:** 'infra' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Postgresql — `svc_postgresql`
- **Purpose:** PostgreSQL is the shared relational datastore for Postgres-family services
(including Authentik's identity tables). It persists whatever the consuming
services write — application user/content rows, audit logs, and OAuth
session data — so those services can function (legitimate interest in
operating the persistence layer, Art. 6(1)(f)). End-user PII present here
is owned by the consuming service; data lifetime and the precise processing
purpose are determined by that service, not by PostgreSQL itself.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`; `end_users`
- **Data categories:** `application_user_data`; `audit_logs`; `oauth_session_data`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** indefinite (lifecycle-managed; deletion via DSAR)
- **Storage:** 'infra' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Redis — `svc_redis`
- **Purpose:** Redis is the platform in-memory cache and session store. It holds
transient cache data and OAuth/Authentik session blobs on behalf of the
consuming services so they perform efficiently (legitimate interest in
operating the cache layer, Art. 6(1)(f)). Session keys can be linked to
downstream end-users, but nothing is durable — the AOF rotates within a
day. Data ownership and purpose remain with the consuming service.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`; `end_users`
- **Data categories:** `cache_data`; `oauth_session_data`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 1 days
- **Storage:** 'infra' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Smtp Stalwart — `svc_smtp-stalwart`
- **Purpose:** Stalwart is the self-hosted mail server (SMTP/IMAP/JMAP). It processes
mailbox contents (message bodies and attachments at rest), SMTP envelope
and header metadata, mailbox credentials (password hashes), and delivery
logs (queue, bounce, DKIM/SPF/DMARC results), in order to send, receive and
store email for tenant mailbox owners (legitimate interest in operating the
mail service, Art. 6(1)(f)). Data subjects include operators, tenant
mailbox owners, and external correspondents whose addresses and message
content appear in inbound/outbound flows. Mailbox retention is ~365 days;
queue/bounce logs are shorter.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`; `mailbox_owners`; `external_correspondents`
- **Data categories:** `mailbox_contents`; `smtp_envelope_metadata`; `mailbox_credentials`; `delivery_logs`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 365 days (~1y)
- **Storage:** 'infra' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Spacetimedb — `svc_spacetimedb`
- **Purpose:** Hosts the operator's SpacetimeDB realtime DB modules. Stores user-defined
tables, table rows, and the cryptographic identity (ctx.sender.identity)
of every module caller. Module-level data subject is operator-defined.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operator`; `module_callers`
- **Data categories:** `module_state`; `operator_identity`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 365 days (~1y)
- **Storage:** 'infra' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Traefik — `svc_traefik`
- **Purpose:** Traefik is the platform edge reverse proxy. Its access and error logs
record request metadata (method, path, status, latency), client source IP
addresses, and User-Agent strings for every HTTP client reaching the edge,
in order to operate, secure and troubleshoot the ingress layer (legitimate
interest in service operation and security, Art. 6(1)(f)). The IP and
User-Agent fields are attributable to end-users; access logs rotate on a
~30-day horizon aligned with Loki retention.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`; `end_users`
- **Data categories:** `request_metadata`; `client_ip_addresses`; `user_agent_strings`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 30 days
- **Storage:** 'infra' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

### observability stack

#### Alloy — `svc_alloy`
- **Purpose:** Alloy is the platform telemetry collection agent: it scrapes host and
container infrastructure metrics and forwards log lines and trace spans
in transit to Prometheus, Loki and Tempo. Processing is necessary to
operate, monitor and troubleshoot the self-hosted platform (legitimate
interest in service operation, Art. 6(1)(f)). End-user data appears only
transiently in transit inside forwarded log/trace payloads; durable
storage and retention are owned by the Loki/Tempo backends, not Alloy.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`; `end_users`
- **Data categories:** `infrastructure_metrics`; `log_lines_in_transit`; `trace_spans_in_transit`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 1 days
- **Storage:** 'observability' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Grafana — `svc_grafana`
- **Purpose:** Grafana is the operator-facing observability console. It processes its own
usage metrics, dashboard view logs, and OAuth session data for the
operators and admins who sign in to view metrics, logs and traces. This is
necessary to operate and monitor the platform for self-observability
(legitimate interest in service operation, Art. 6(1)(f)). No tenant
end-users are data subjects here — only the operator/admin staff who use
the console.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operator`; `admins`
- **Data categories:** `usage_metrics`; `dashboard_view_logs`; `oauth_session_data`
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
- **Data categories:** `timeseries_metrics`; `bucket_metadata`; `oauth_session_data`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 365 days (~1y)
- **Storage:** 'observability' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Loki — `svc_loki`
- **Purpose:** Loki is the platform log-aggregation backend. It stores log lines,
hostname labels and request metadata (which may include user agents and
source IPs harvested from nginx/Wing access logs) so the operator can
search, correlate and debug across services (legitimate interest in
service operation and security, Art. 6(1)(f)). End-user data appears
incidentally inside ingested access-log lines; retention follows the Loki
schema_config horizon (~30 days).
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`; `end_users`
- **Data categories:** `log_lines`; `hostname_labels`; `request_metadata`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 30 days
- **Storage:** 'observability' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Prometheus — `svc_prometheus`
- **Purpose:** Prometheus is the platform metrics time-series backend. It stores
infrastructure metrics and their hostname labels scraped from exporters so
the operator can monitor capacity, health and alerting (legitimate
interest in service operation, Art. 6(1)(f)). Metrics are machine-level;
no end-user identifiers are stored. Retention follows prometheus_retention
(~30 days).
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`
- **Data categories:** `infrastructure_metrics`; `hostname_labels`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 30 days
- **Storage:** 'observability' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Tempo — `svc_tempo`
- **Purpose:** Tempo is the platform distributed-tracing backend. It stores trace spans
and their request metadata (which may include user-agent strings and
request paths) so the operator can debug latency and reconstruct request
flows across services (legitimate interest in service operation,
Art. 6(1)(f)). End-user data appears incidentally inside span attributes;
retention is ~14 days.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`; `end_users`
- **Data categories:** `trace_spans`; `request_metadata`
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
- **Data subjects:** `operators`; `end_users`
- **Data categories:** `ebook_metadata`; `reading_progress`; `oauth_session_data`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 365 days (~1y)
- **Storage:** 'iiab' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Face — `svc_face`
- **Purpose:** Renders a per-user web desktop: which apps the signed-in user can launch
(from the Wing catalog, filtered by their Authentik tier) and a browser of
their own files in the class-3 per-user tree. Identity comes from the
Authentik forward-auth headers; the shell stores no independent account.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `end_users`
- **Data categories:** `username`; `email`
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
- **Data subjects:** `operators`; `household_members`
- **Data categories:** `device_telemetry`; `sensor_history`; `automation_definitions`; `user_accounts`; `oauth_session_data`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 365 days (~1y)
- **Storage:** 'iiab' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Jellyfin — `svc_jellyfin`
- **Purpose:** Hosts the operator's media library (movies / TV / music). Stores user
accounts (per-family-member profiles), watch history, and library
metadata.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`; `end_users`
- **Data categories:** `user_accounts`; `watch_history`; `media_metadata`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 365 days (~1y)
- **Storage:** 'iiab' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Keap — `svc_keap`
- **Purpose:** Per-user knowledge-exploration state (learning progress, todos, saved
bookmarks), operator-curated taxonomy content links, and captures
submitted for human review through the unified intake: the companion
userscript, nOS agents, and field DEVICES (AR glasses / mobile
companions posting text, transcripts, geo-tagged moments and
media-by-reference to /ingest/v1).
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `end_users`
- **Data categories:** `username`; `email`; `behavioural_data`; `user_generated_content`; `location_data`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 365 days (~1y)
- **Storage:** 'iiab' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Kiwix — `svc_kiwix`
- **Purpose:** Operator-hosted offline content reader (Wikipedia, Gutenberg, ZIM archives). Forward-auth gate ensures only
Authentik-authenticated principals reach the service.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`; `end_users`
- **Data categories:** `zim_access_logs`; `oauth_session_data`
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
- **Data categories:** `captured_email_bodies`; `smtp_envelope_metadata`; `oauth_session_data`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 7 days
- **Storage:** 'iiab' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Mcp Gateway — `svc_mcp-gateway`
- **Purpose:** The MCP Gateway (mcpo) proxies Model Context Protocol tool calls for local
agents. It processes MCP request metadata (tool invocations and their
parameters) and access logs for the read-only filesystem and local git
repositories it exposes, in order to mediate and audit agent tool access
(legitimate interest in service operation, Art. 6(1)(f)). Subjects are the
operator and automated agent systems (e.g. Open WebUI agents); no tenant
end-user identities are processed.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`; `automated_systems`
- **Data categories:** `mcp_request_metadata`; `filesystem_access_logs`; `git_repo_access_logs`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 30 days
- **Storage:** 'iiab' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Miniflux — `svc_miniflux`
- **Purpose:** Hosts the operator's RSS aggregator. Stores feed subscriptions,
read/unread state, starred items, and the OIDC session link.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`; `end_users`
- **Data categories:** `feed_subscriptions`; `read_state`; `oauth_session_data`; `email`
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
- **Data subjects:** `operators`; `end_users`
- **Data categories:** `workflow_definitions`; `execution_history`; `encrypted_credentials`; `oauth_session_data`; `email`
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
- **Data subjects:** `operators`; `end_users`
- **Data categories:** `file_storage`; `contacts`; `calendars`; `chat_messages`; `user_accounts`; `oauth_session_data`; `email`
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
- **Data categories:** `flow_definitions`; `credential_nodes`; `oauth_session_data`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 365 days (~1y)
- **Storage:** 'iiab' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Ntfy — `svc_ntfy`
- **Purpose:** Operator-hosted pub/sub HTTP push notifications server. Forward-auth gate ensures only
Authentik-authenticated principals reach the service.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`; `end_users`
- **Data categories:** `topic_messages`; `subscriber_endpoints`; `oauth_session_data`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 30 days
- **Storage:** 'iiab' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Offline Maps — `svc_offline-maps`
- **Purpose:** The offline-maps tile server serves pre-rendered map tiles to browser
clients. It processes tile request logs (bounding box, zoom level, tile
coordinates) and hostname labels for operational monitoring of the map
service (legitimate interest in service operation, Art. 6(1)(f)). The
request logs can be attributed to browsing end-users; no account or
identity data is collected.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`; `end_users`
- **Data categories:** `tile_request_logs`; `hostname_labels`
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
- **Data subjects:** `operators`; `end_users`
- **Data categories:** `chat_messages`; `prompt_history`; `user_accounts`; `oauth_session_data`; `email`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 365 days (~1y)
- **Storage:** 'iiab' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Rustfs — `svc_rustfs`
- **Purpose:** RustFS is the S3-compatible object store used as the nightly backup target
and general blob store. It holds object-storage blobs (backup tarballs and
bucket contents) and S3 GET/PUT access logs, in order to provide durable
backup and object storage for the platform (legitimate interest in service
operation and resilience, Art. 6(1)(f)). Operators administer it; any
end-user PII inside backup tarballs is derived from the originating service
and governed by that service's record. Retention is the backup horizon
(~90 days), tightened by per-bucket lifecycle policies.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`
- **Data categories:** `object_storage_blobs`; `access_logs`
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
- **Data subjects:** `operators`; `end_users`
- **Data categories:** `imap_smtp_credentials`; `webmail_session_data`; `oauth_session_data`; `email_cache_metadata`
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
- **Data categories:** `monitor_status`; `uptime_history`; `oauth_session_data`
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
- **Data subjects:** `operators`; `end_users`
- **Data categories:** `encrypted_credentials`; `master_password_hash`; `encrypted_attachments`; `oauth_session_data`; `email`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** indefinite (lifecycle-managed; deletion via DSAR)
- **Storage:** 'iiab' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Watchtower — `svc_watchtower`
- **Purpose:** Watchtower automates container image updates. It processes container
metadata (image names, tags, IDs, restart counts) and update event logs
(what was pulled, when, success/failure), in order to keep the container
estate patched and report on update activity (legitimate interest in
service operation and security, Art. 6(1)(f)). Only operators are data
subjects; no end-user data is processed. Logs rotate (max-size 10m,
max-file 3).
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`
- **Data categories:** `container_metadata`; `update_event_logs`
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
- **Data subjects:** `operators`; `end_users`; `anonymous_visitors`
- **Data categories:** `blog_content`; `comments`; `user_accounts`; `oauth_session_data`; `email`
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
- **Data subjects:** `end_users`; `operators`
- **Data categories:** `name`; `email`; `ip_address`; `signature_image`; `document_content`
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
- **Data categories:** `agent_run_metadata`; `system_facts`; `cybersec_metadata`
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
- **Data subjects:** `operators`; `end_users`
- **Data categories:** `email_metadata`; `address_book_entries`; `ui_preferences`
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
- **Data categories:** `credentials`; `authentication_metadata`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** indefinite (lifecycle-managed; deletion via DSAR)
- **Storage:** 'apps' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Qdrant — `svc_qdrant`
- **Purpose:** Qdrant is the vector database backing agent memory and advisory retrieval.
It stores agent prompt-context embeddings (which may include operator data),
advisory text (CVE summaries, vendor advisories), and vector metadata
(collection names, point ids, payload schemas), in order to provide
semantic memory and retrieval for the platform's AI agents (legitimate
interest in research / agent operation, not contract-bound, Art. 6(1)(f)).
Subjects are operators and automated agent systems; Bone redacts operator
email before upsert. Points expire on a ~365-day nightly Pulse rebuild.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`; `automated_systems`
- **Data categories:** `agent_prompt_context`; `advisory_text`; `vector_metadata`
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
- **Data categories:** `workspace_files`; `git_credentials`; `oauth_session_data`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 365 days (~1y)
- **Storage:** 'devops' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Gitea — `svc_gitea`
- **Purpose:** Gitea is the self-hosted Git forge. It processes developer identity
metadata (username, email, full name), authentication credentials
(password hash, OAuth tokens), user-authored source code repositories, and
an activity audit log (push events, login history), in order to provide
source-code hosting and collaboration to tenant developers. Providing the
forge to a registered developer is contractual (Art. 6(1)(b)). Accounts
persist while active; deletion is handled via the Art-17 erasure path.
- **Legal basis (Art. 6):** `contract`
- **Data subjects:** `operators`; `end_users`
- **Data categories:** `identity_metadata`; `authentication_credentials`; `source_code`; `audit_log_entries`
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
- **Data subjects:** `operators`; `end_users`
- **Data categories:** `repository_content`; `issues_and_mrs`; `ci_artifacts`; `user_accounts`; `oauth_session_data`; `email`
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
- **Data categories:** `agent_runs`; `task_artifacts`; `oauth_session_data`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 365 days (~1y)
- **Storage:** 'devops' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Woodpecker — `svc_woodpecker`
- **Purpose:** Woodpecker is the self-hosted CI engine wired to Gitea. It processes CI
pipeline logs (build output, which may embed commit metadata), Gitea OAuth2
session data, and commit-author metadata (author name + email per pipeline
trigger), in order to run continuous-integration pipelines for repository
contributors (legitimate interest in operating CI, Art. 6(1)(f)). Subjects
are the operator and repo developers triggering pipelines; all execution is
local with no external runners. CI logs auto-prune (~90 days).
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operator`; `developers`
- **Data categories:** `ci_pipeline_logs`; `oauth_session_data`; `commit_author_metadata`
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
- **Data subjects:** `operators`; `end_users`
- **Data categories:** `wiki_content`; `revision_history`; `user_accounts`; `oauth_session_data`; `email`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 365 days (~1y)
- **Storage:** 'b2b' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Erpnext — `svc_erpnext`
- **Purpose:** ERPNext is the business ERP/CRM platform. It processes employee and
customer identity metadata, financial records (invoices, expenses, GL
entries), HR and payroll data, CRM customer/order data, and an audit log,
in order to run the operator's accounting, HR and customer-relationship
operations. Most of this is necessary to perform contracts with employees
and customers (Art. 6(1)(b)), with statutory accounting-retention
obligations driving the ~7-year horizon. Subjects include operators,
tenant employees/customers (end-users), and third-party CRM contacts.
- **Legal basis (Art. 6):** `contract`
- **Data subjects:** `operators`; `end_users`; `third_parties`
- **Data categories:** `identity_metadata`; `financial_records`; `hr_data`; `customer_data`; `audit_log_entries`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 2555 days (~7y)
- **Storage:** 'b2b' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Firefly — `svc_firefly`
- **Purpose:** Operator-hosted personal finance manager. Forward-auth gate ensures only
Authentik-authenticated principals reach the service.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`; `end_users`
- **Data categories:** `transaction_history`; `account_balances`; `tags`; `oauth_session_data`
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
- **Data subjects:** `operators`; `support_agents`; `end_users`
- **Data categories:** `support_conversations`; `ticket_metadata`; `customer_emails`; `internal_notes`; `user_accounts`; `oauth_session_data`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 1095 days (~3y)
- **Storage:** 'b2b' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Hedgedoc — `svc_hedgedoc`
- **Purpose:** Hosts the operator's HedgeDoc collaborative markdown notes. Stores
documents, edit history, and OIDC session links.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`; `end_users`
- **Data categories:** `document_content`; `edit_history`; `oauth_session_data`; `email`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 365 days (~1y)
- **Storage:** 'b2b' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Onlyoffice — `svc_onlyoffice`
- **Purpose:** Operator-hosted collaborative office editor backend. Forward-auth gate ensures only
Authentik-authenticated principals reach the service.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`; `end_users`
- **Data categories:** `document_edits`; `collaboration_sessions`; `oauth_session_data`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 365 days (~1y)
- **Storage:** 'b2b' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Outline — `svc_outline`
- **Purpose:** Hosts the operator's Outline collaborative wiki. Stores documents,
document revisions, comments, user accounts, and OIDC session data.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`; `end_users`
- **Data categories:** `wiki_content`; `revision_history`; `comments`; `user_accounts`; `oauth_session_data`; `email`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 365 days (~1y)
- **Storage:** 'b2b' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

### voip stack

#### Freepbx — `svc_freepbx`
- **Purpose:** FreePBX/Asterisk is the self-hosted telephony PBX. It processes call
detail records (caller/callee numbers, duration, codec), voicemail
recordings, SIP/IAX extension credentials (hashed), and operator-authored
dialplan routing rules, in order to provide and operate telephony for the
organisation (legitimate interest in running the phone system,
Art. 6(1)(f)). Subjects include PBX admins, extension owners, and external
callers whose numbers appear in CDRs. CDRs rotate on a ~90-day horizon;
voicemail retention follows operator policy.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`; `extension_users`; `external_callers`
- **Data categories:** `call_metadata`; `voicemail_recordings`; `extension_credentials`; `dialplan_state`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 90 days
- **Storage:** 'voip' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

### engineering stack

#### Qgis Server — `svc_qgis-server`
- **Purpose:** QGIS Server is the backend-only OGC geospatial service (WMS/WFS). It
processes OGC request logs (GetMap / GetFeature parameters) and hostname
labels for operational monitoring of the map/feature endpoints (legitimate
interest in service operation, Art. 6(1)(f)). Subjects are the operator and
automated GIS clients consuming the endpoints; no account or end-user
identity data is collected.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`; `automated_systems`
- **Data categories:** `ogc_request_logs`; `hostname_labels`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 30 days
- **Storage:** 'engineering' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

### data stack

#### Metabase — `svc_metabase`
- **Purpose:** Hosts the operator's Metabase BI dashboards. Stores question /
dashboard / collection metadata, query history, user accounts.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`
- **Data categories:** `dashboard_definitions`; `query_history`; `user_accounts`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 365 days (~1y)
- **Storage:** 'data' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Superset — `svc_superset`
- **Purpose:** Hosts the operator's BI dashboards (Apache Superset). Stores dataset
metadata, dashboard definitions, query history, and user sessions.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`
- **Data categories:** `dashboard_definitions`; `query_history`; `user_accounts`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 365 days (~1y)
- **Storage:** 'data' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

### host stack

#### Backrest — `svc_backrest`
- **Purpose:** backrest orchestrates restic backups (off-site copy #2) + provides the
restore UI. It reads and snapshots whatever host paths the operator adds as
backup sources — which may include per-user data trees — and stores restic
snapshots in the configured repositories. It is an operator-facing admin
tool; it holds no data-subject records of its own beyond the contents of
the backups it manages and its own operation logs.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`
- **Data categories:** `backup_snapshots`; `backup_operation_metadata`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** transient (not persisted)
- **Storage:** 'host' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Backup — `svc_backup`
- **Purpose:** Nightly operational backup (copy #1). Takes logical dumps of MariaDB and
PostgreSQL, online copies of the Wing and KEAP SQLite stores, tar archives
of host service data dirs, and ~/.nos state; encrypts them (AES-256-CBC,
pbkdf2) and writes them to the local RustFS bucket. Exists for disaster
recovery and for the pre-wipe safety copy taken before a removal. It is
machinery, not a service: no data subject ever interacts with it.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`; `tenant_users`
- **Data categories:** `database_dumps`; `service_data_directories`; `operational_state`; `backup_operation_metadata`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 30 days
- **Storage:** 'host' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Cortex — `svc_cortex`
- **Purpose:** Cortex is the estate's reasoning organ: it typechecks agent-authored
cortex-lang programs against the curated taxonomy and the controlled verb
vocabulary, and reports the ontology/opcode/database drift axes on
/health. Its store is materialised from the repository (spine + canonical
tree + the generated nOS self-model).

SINCE S2 (docs/archive/cortex-corpus-parallel.md) it ALSO mirrors the
per-user filesystem tree — {{ nos_data_root }}/tenants/<slug>/users/<uid>/
{documents,library,inbox} — as owner-scoped knowledge objects, and accepts
consolidator datapoints on /ingest/v1/capture. The previous row said this
service "holds NO per-user content and NO knowledge_objects corpus"; that
stopped being true the moment fs-sync was ported, and it is corrected here
rather than at the next audit. The mirror is READ-ONLY with respect to the
user tree: the organ opens no file for writing, and every id and every
visibility decision is derived from directory NAMES, never from filesystem
ownership. Per-user data is duplicated from KEAP's identical mirror, from
the same host source, so this adds a second COPY of an already-registered
category — no new category of subject data enters the estate.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`; `tenant_users`
- **Data categories:** `taxonomy_tree`; `validate_requests`; `user_documents`; `consolidator_datapoints`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** indefinite (lifecycle-managed; deletion via DSAR)
- **Storage:** 'host' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

#### Wing — `svc_wing`
- **Purpose:** Operator-hosted security-research dashboard (FrankenPHP host daemon). Forward-auth gate ensures only
Authentik-authenticated principals reach the service.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`
- **Data categories:** `systems_inventory`; `remediation_items`; `audit_events`; `oauth_session_data`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** indefinite (lifecycle-managed; deletion via DSAR)
- **Storage:** 'host' compose stack on host (Docker volumes)
- **Security measures:** platform baseline (see above)

### host / non-stack

#### conductor — `agent_conductor`
- **Purpose:** Verifies the platform end-to-end after a converge: reads Wing state, health
endpoints and the Pulse job registry, then reports findings. Estate
operation and assurance (legitimate interest, Art. 6(1)(f)). The prompt and
the material it gathers are sent to a hosted model for reasoning.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`
- **Data categories:** `estate_health_telemetry`; `job_registry_metadata`; `operator_authored_prompts`
- **Recipients / processors:** **MiniMax** (unverified — international endpoint api.minimax.io; entity and seat not established) — LLM inference via the Anthropic-compatible endpoint (SDK adapter, tool loop driven by AgentKit). The bound backend for this ceremony. · safeguard: None established. Recorded as UNVERIFIED rather than asserted; the binding gate refuses a backend this record does not name, so this entry is what permits the routing and must not be written as a claim it cannot support.; **Anthropic, PBC** (US) — LLM inference when this ceremony is driven on the claude-CLI path rather than the bound backend (--print) · safeguard: None claimed. Assess SCCs / Art. 46 before this is relied on.
- **Transfers outside EU:** **Yes**
- **Retention:** indefinite (lifecycle-managed; deletion via DSAR)
- **Storage:** host service (non-Docker / launchd)
- **Security measures:** platform baseline (see above)

#### curator — `agent_curator`
- **Purpose:** Reconciles and reshapes the KEAP taxonomy — the librarian's active sibling.
Estate knowledge maintenance (legitimate interest, Art. 6(1)(f)). What
travels is curated public-knowledge content, not tenant data.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`
- **Data categories:** `knowledge_corpus_content`; `taxonomy_structure`
- **Recipients / processors:** **MiniMax** (unverified — international endpoint api.minimax.io; entity and seat not established) — LLM inference via the Anthropic-compatible endpoint (SDK adapter, tool loop driven by AgentKit). The bound backend for this ceremony. · safeguard: None established. Recorded as UNVERIFIED rather than asserted; the binding gate refuses a backend this record does not name, so this entry is what permits the routing and must not be written as a claim it cannot support.; **Anthropic, PBC** (US) — LLM inference when this ceremony is driven on the claude-CLI path rather than the bound backend (--print) · safeguard: None claimed. Assess SCCs / Art. 46 before this is relied on.
- **Transfers outside EU:** **Yes**
- **Retention:** indefinite (lifecycle-managed; deletion via DSAR)
- **Storage:** host service (non-Docker / launchd)
- **Security measures:** platform baseline (see above)

#### inspektor — `agent_inspektor`
- **Purpose:** Would survey the platform's security posture by driving scan substrates and
analysing findings. DECLARED, NOT PERFORMED: `metadata.runner_status` is
`deferred` — the agent ships as an AgentKit contract with no live execution
and no registered Pulse ceremony, so no processing occurs and nothing is
transferred.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`
- **Data categories:** `none_processed_while_deferred`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** indefinite (lifecycle-managed; deletion via DSAR)
- **Storage:** host service (non-Docker / launchd)
- **Security measures:** platform baseline (see above)

#### jeff — `agent_jeff`
- **Purpose:** Assisting the operator with the estate: reading Wing state, answering questions, and proposing work as typed chains. Estate operation under legitimate interest, Art. 6(1)(f). Inputs are whatever the operator says or types, which is why the local twin exists at all.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`
- **Data categories:** `operator_authored_prompts`; `estate_health_telemetry`; `operator_speech_transcripts`
- **Recipients / processors:** **on-device (operator's own hardware)** (CZ — this host) — LLM inference on this host via ollama's OpenAI-compatible surface on loopback. No third party sees the prompt, so there is no processor in the Article-28 sense; this entry says so rather than leaving the field blank. · safeguard: Not applicable. No transfer occurs, which is stronger than any safeguard could describe.
- **Transfers outside EU:** No
- **Retention:** 90 days
- **Storage:** host service (non-Docker / launchd)
- **Security measures:** platform baseline (see above)

#### jeff-cloud — `agent_jeff-cloud`
- **Purpose:** Assisting the operator with the estate when the local model is not enough: reading Wing state, answering questions, proposing typed chains. Estate operation under legitimate interest, Art. 6(1)(f).
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`
- **Data categories:** `operator_authored_prompts`; `estate_health_telemetry`; `operator_speech_transcripts`
- **Recipients / processors:** **MiniMax** (unverified — international endpoint api.minimax.io; entity and seat not established) — LLM inference via the Anthropic-compatible endpoint (SDK adapter, tool loop driven by AgentKit). The bound backend for this agent. · safeguard: None established. Recorded as UNVERIFIED rather than asserted; the binding gate refuses a backend this record does not name, so this entry is what permits the routing and must not be written as a claim it cannot support.
- **Transfers outside EU:** **Yes**
- **Retention:** 90 days
- **Storage:** host service (non-Docker / launchd)
- **Security measures:** platform baseline (see above)

#### librarian — `agent_librarian`
- **Purpose:** Surfaces prior context — earlier agent runs, remediation history, KEAP
knowledge nodes — so a question already answered is not re-answered.
Estate operation (legitimate interest, Art. 6(1)(f)).
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`
- **Data categories:** `agent_run_history`; `remediation_queue_records`; `knowledge_corpus_content`
- **Recipients / processors:** **Anthropic, PBC** (US) — LLM inference for the ceremony's reasoning (claude CLI, --print) · safeguard: None claimed. Assess SCCs / Art. 46 before this is relied on.; **MiniMax** (unverified — international endpoint api.minimax.io; entity and seat not established) — LLM inference via the Anthropic-compatible endpoint (SDK adapter, tool loop driven by AgentKit) · safeguard: None claimed, and none assessed. No SCCs, adequacy finding or derogation has been identified for this transfer.
- **Transfers outside EU:** **Yes**
- **Retention:** indefinite (lifecycle-managed; deletion via DSAR)
- **Storage:** host service (non-Docker / launchd)
- **Security measures:** platform baseline (see above)

#### migration-author — `agent_migration-author`
- **Purpose:** Promotes a reviewed upgrade recipe into the committed codebase change.
Estate maintenance (legitimate interest, Art. 6(1)(f)). Authoring a real
code change sends repository source, and the resulting branch carries
commit metadata.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`; `commit_authors`
- **Data categories:** `repository_source`; `commit_metadata`
- **Recipients / processors:** **Anthropic, PBC** (US) — LLM inference for the ceremony's reasoning (claude CLI, --print) · safeguard: None claimed. Assess SCCs / Art. 46 before this is relied on.
- **Transfers outside EU:** **Yes**
- **Retention:** indefinite (lifecycle-managed; deletion via DSAR)
- **Storage:** host service (non-Docker / launchd)
- **Security measures:** platform baseline (see above)

#### ops-extract — `agent_ops-extract`
- **Purpose:** Measuring how well a locally-hosted model extracts fields from short business documents, so the estate can decide which model size its ops plane needs. The inputs are the hand-written fixtures in state/ops-task-families/, not customer documents.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `none`
- **Data categories:** `business_document_fixtures`
- **Recipients / processors:** **on-device (operator's own hardware)** (CZ — this host) — LLM inference on this host via ollama's OpenAI-compatible surface on loopback. There is no third party: the prompt does not leave the machine, so there is no processor in the Article-28 sense and this entry exists to say so rather than leave the field blank. · safeguard: Not applicable. No transfer occurs, which is a stronger position than any safeguard could describe.
- **Transfers outside EU:** No
- **Retention:** transient (not persisted)
- **Storage:** host service (non-Docker / launchd)
- **Security measures:** platform baseline (see above)

#### ops-extract-cloud — `agent_ops-extract-cloud`
- **Purpose:** Measuring how well a HOSTED model extracts fields from short business documents, against the identical task the local twin runs, so the estate can decide whether the cloud is worth the transfer. The inputs are the hand-written fixtures in state/ops-task-families/, not customer documents — which is what makes this transfer proportionate to run at all.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `none`
- **Data categories:** `business_document_fixtures`
- **Recipients / processors:** **MiniMax** (unverified — international endpoint api.minimax.io; entity and seat not established) — LLM inference via the Anthropic-compatible endpoint (SDK adapter, single call, no tool loop) · safeguard: None claimed, and none assessed. No SCCs, adequacy finding or derogation has been identified for this transfer.
- **Transfers outside EU:** **Yes**
- **Retention:** transient (not persisted)
- **Storage:** host service (non-Docker / launchd)
- **Security measures:** platform baseline (see above)

#### ops-triage — `agent_ops-triage`
- **Purpose:** Measuring how well a locally-hosted model triages the estate's own reported weaknesses, so the loop can eventually stop spending a model run on a row no patch can close. The inputs are the fixtures in state/ops-task-families/weakness-triage/ — real findings, rewritten by hand with their source ids removed.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `none`
- **Data categories:** `own_infrastructure_findings`
- **Recipients / processors:** **on-device (operator's own hardware)** (CZ — this host) — LLM inference on this host via ollama's OpenAI-compatible surface on loopback. No third party: the prompt does not leave the machine, so there is no processor in the Article-28 sense and this entry says so rather than leaving the field blank. · safeguard: Not applicable. No transfer occurs.
- **Transfers outside EU:** No
- **Retention:** transient (not persisted)
- **Storage:** host service (non-Docker / launchd)
- **Security measures:** platform baseline (see above)

#### ops-triage-cloud — `agent_ops-triage-cloud`
- **Purpose:** Measuring whether a hosted model triages the estate's own reported weaknesses better than the local twin, on the identical task, so the operator can decide whether the transfer buys anything.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `none`
- **Data categories:** `own_infrastructure_findings`
- **Recipients / processors:** **MiniMax** (unverified — international endpoint api.minimax.io; entity and seat not established) — LLM inference via the Anthropic-compatible endpoint (SDK adapter, single call, no tool loop) · safeguard: None claimed, and none assessed. No SCCs, adequacy finding or derogation has been identified for this transfer.
- **Transfers outside EU:** **Yes**
- **Retention:** transient (not persisted)
- **Storage:** host service (non-Docker / launchd)
- **Security measures:** platform baseline (see above)

#### proposer — `agent_proposer`
- **Purpose:** Authoring a bounded change to this estate's own source in response to a weakness it found in itself. No personal data is read or transmitted.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `none`
- **Data categories:** `source_code`; `defect_records`
- **Recipients / processors:** **MiniMax** (unverified — international endpoint api.minimax.io; entity and seat not established) — LLM inference via the Anthropic-compatible endpoint (SDK adapter, tool loop driven by AgentKit) · safeguard: None claimed, and none assessed. No SCCs, adequacy finding or derogation has been identified for this transfer.
- **Transfers outside EU:** **Yes**
- **Retention:** transient (not persisted)
- **Storage:** host service (non-Docker / launchd)
- **Security measures:** platform baseline (see above)

#### surveyor — `agent_surveyor`
- **Purpose:** Reads the estate's declared structure (service manifest, plugin
manifests, system documentation) and its running shape (container
inventory, Wing surface indexes) to advise which of it is worth
displaying. Estate operation (legitimate interest, Art. 6(1)(f)).

What travels to the processor is STRUCTURAL: service identifiers,
declared ports and domains, documentation prose. Operator and agent
identifiers reach it only where they appear in the surface indexes
it reads — the ceremony asks for counts and shapes, not for rows.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`; `automation_identities`
- **Data categories:** `declared_state_manifest`; `service_plugin_manifests`; `system_documentation`; `surface_inventory`
- **Recipients / processors:** **MiniMax** (unverified — international endpoint api.minimax.io; entity and seat not established) — LLM inference via the Anthropic-compatible endpoint (SDK adapter, tool loop driven by AgentKit). The bound backend for this ceremony. · safeguard: None established. Recorded as UNVERIFIED rather than asserted; the binding gate refuses a backend this record does not name, so this entry is what permits the routing and must not be written as a claim it cannot support.; **Anthropic, PBC** (US) — LLM inference when this ceremony is driven on the claude-CLI path rather than the bound backend (--print) · safeguard: None claimed. Assess SCCs / Art. 46 before this is relied on.
- **Transfers outside EU:** **Yes**
- **Retention:** indefinite (lifecycle-managed; deletion via DSAR)
- **Storage:** host service (non-Docker / launchd)
- **Security measures:** platform baseline (see above)

#### upgrade-architect — `agent_upgrade-architect`
- **Purpose:** Authors upgrade recipes for the version gaps the advisor cannot act on.
Estate maintenance (legitimate interest, Art. 6(1)(f)). Recipe authoring
sends repository source — role defaults, task files, templates — for
reasoning.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`
- **Data categories:** `repository_source`; `installed_version_inventory`
- **Recipients / processors:** **Anthropic, PBC** (US) — LLM inference for the ceremony's reasoning (claude CLI, --print) · safeguard: None claimed. Assess SCCs / Art. 46 before this is relied on.
- **Transfers outside EU:** **Yes**
- **Retention:** indefinite (lifecycle-managed; deletion via DSAR)
- **Storage:** host service (non-Docker / launchd)
- **Security measures:** platform baseline (see above)

#### Alert Relay — `svc_alert-relay`
- **Purpose:** Deliver Prometheus firing alerts to the operator via the A9 notification spine, so a rule that evaluates is a rule someone reads
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`
- **Data categories:** `service_health_metadata`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 365 days (~1y)
- **Storage:** host service (non-Docker / launchd)
- **Security measures:** platform baseline (see above)

#### Alloy Docker Metrics — `svc_alloy-docker-metrics`
- **Purpose:** Scrapes per-container Docker infrastructure metrics (CPU, memory,
network, restart counts) and tails container stdout/stderr logs so the
operator can monitor and troubleshoot the Docker workload (legitimate
interest in service operation, Art. 6(1)(f)). End-user data only appears
incidentally inside container access logs; high log volume means a short
retention horizon.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`; `end_users`
- **Data categories:** `infrastructure_metrics`; `container_logs`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 7 days
- **Storage:** host service (non-Docker / launchd)
- **Security measures:** platform baseline (see above)

#### Alloy Host Metrics — `svc_alloy-host-metrics`
- **Purpose:** Scrapes host-level infrastructure metrics (CPU, memory, disk and network
utilisation) from the node exporter so the operator can monitor capacity
and health of the host (legitimate interest in service operation,
Art. 6(1)(f)). No end-user identifiers are collected — host metrics are
machine-level, not subject-level.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`
- **Data categories:** `infrastructure_metrics`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 30 days
- **Storage:** host service (non-Docker / launchd)
- **Security measures:** platform baseline (see above)

#### Alloy Syslog — `svc_alloy-syslog`
- **Purpose:** Tails host operational logs (nginx and php-fpm access/error) and the
platform audit trail (Bone, Wing, Pulse and agent runs) and ships them to
Loki so the operator can debug failures and reconstruct an audit lineage
(legitimate interest in service operation and security, Art. 6(1)(f)).
End-user data appears incidentally inside host nginx access lines (request
paths, source IPs); durable retention is owned by Loki, not this agent.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`; `end_users`
- **Data categories:** `operational_logs`; `audit_trail_logs`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 14 days
- **Storage:** host service (non-Docker / launchd)
- **Security measures:** platform baseline (see above)

#### Apex — `svc_apex`
- **Purpose:** Serves the public anatomy page at the root domain — a static,
operator-signed projection of the estate's structure for anonymous
visitors (the "This is AIT" front door). The page carries no live
state, no user accounts, no cookies, no forms and no telemetry; the
only personal data processed is standard web-server access metadata
(visitor IP address, user agent, request path) written to rotated
container logs for security monitoring of a public endpoint.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `anonymous_visitors`
- **Data categories:** `access_log_ip_addresses`; `user_agent_strings`; `request_paths`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 30 days
- **Storage:** host service (non-Docker / launchd)
- **Security measures:** platform baseline (see above)

#### Authentik Tofu Drift — `svc_authentik-tofu-drift`
- **Purpose:** Detect configuration drift between the live Authentik SSO tenant and its OpenTofu-managed desired state; notify the operator with the plan summary
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`
- **Data categories:** `iam_configuration_metadata`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 365 days (~1y)
- **Storage:** host service (non-Docker / launchd)
- **Security measures:** platform baseline (see above)

#### Discovery — `svc_discovery`
- **Purpose:** Consistency checking between declared configuration and observed runtime state
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`
- **Data categories:** `software_inventory`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 365 days (~1y)
- **Storage:** host service (non-Docker / launchd)
- **Security measures:** platform baseline (see above)

#### Gdpr Breach — `svc_gdpr-breach`
- **Purpose:** Track GDPR Art-33/34 + NIS2/ZKB breach-notification deadlines and escalate overdue regulator notifications
- **Legal basis (Art. 6):** `legal_obligation`
- **Data subjects:** `operators`
- **Data categories:** `breach_incident_metadata`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** indefinite (lifecycle-managed; deletion via DSAR)
- **Storage:** host service (non-Docker / launchd)
- **Security measures:** platform baseline (see above)

#### Gitleaks — `svc_gitleaks`
- **Purpose:** Secret detection in operator-managed source repositories (nOS repo)
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`
- **Data categories:** `source_code_metadata`; `partial_credentials`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 365 days (~1y)
- **Storage:** host service (non-Docker / launchd)
- **Security measures:** platform baseline (see above)

#### Grafana Keap — `svc_grafana-keap`
- **Purpose:** Composition wiring that provisions the keap.db SQLite datasource into
Grafana so operators can observe the knowledge layer — taxonomy size and
shape, typed relations, corpus objects, DataTables row counts — alongside
the operational Wing dashboards (legitimate interest in service operation,
Art. 6(1)(f)). It stores nothing itself; the retention horizon is owned by
keap-base. Read-only, admin-tier access.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`; `tenant_users`
- **Data categories:** `knowledge_taxonomy`; `knowledge_corpus_metadata`; `datatable_rows`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** transient (not persisted)
- **Storage:** host service (non-Docker / launchd)
- **Security measures:** platform baseline (see above)

#### Grafana Loki — `svc_grafana-loki`
- **Purpose:** Composition wiring that provisions the Loki datasource into Grafana. It
processes only the log-query metadata of the operators who run Explore
queries against Loki (legitimate interest in service operation,
Art. 6(1)(f)); it stores nothing itself — the log-retention horizon is
owned by loki-base.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`
- **Data categories:** `log_query_metadata`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** transient (not persisted)
- **Storage:** host service (non-Docker / launchd)
- **Security measures:** platform baseline (see above)

#### Grafana Prometheus — `svc_grafana-prometheus`
- **Purpose:** Composition wiring that provisions the Prometheus datasource into Grafana.
It surfaces infrastructure metrics piped through from prometheus-base to
operators viewing dashboards (legitimate interest in service operation,
Art. 6(1)(f)). It persists nothing itself; the metric-retention horizon is
owned by prometheus-base. No end-user identifiers are involved.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`
- **Data categories:** `infrastructure_metrics`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 30 days
- **Storage:** host service (non-Docker / launchd)
- **Security measures:** platform baseline (see above)

#### Grafana Tempo — `svc_grafana-tempo`
- **Purpose:** Composition wiring that provisions the Tempo datasource into Grafana so
operators can inspect distributed traces. It surfaces trace spans and
their request metadata for debugging and performance analysis (legitimate
interest in service operation, Art. 6(1)(f)). It stores nothing itself;
the trace-retention horizon is owned by tempo-base.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`
- **Data categories:** `trace_spans`; `request_metadata`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** 14 days
- **Storage:** host service (non-Docker / launchd)
- **Security measures:** platform baseline (see above)

#### Grafana Wing — `svc_grafana-wing`
- **Purpose:** Composition wiring that provisions the wing.db SQLite datasource into
Grafana for the playbook-run and AI-agent dashboards. It surfaces
playbook event metadata (task/play/handler lifecycle) and agent-session
telemetry (run outcomes, token tallies) to operators (legitimate interest
in service operation, Art. 6(1)(f)). It stores nothing itself; the
retention horizon is owned by wing-base. Operator-only data subjects.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`
- **Data categories:** `playbook_event_metadata`; `agent_session_telemetry`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** transient (not persisted)
- **Storage:** host service (non-Docker / launchd)
- **Security measures:** platform baseline (see above)

#### Hermes — `svc_hermes`
- **Purpose:** Hermes is the operator's local cross-channel agent gateway. It receives
prompts from the operator (web UI / CLI / — when explicitly enabled —
messaging channels), forwards them to Ollama (running on the same host with
the MLX backend), and returns generated text. No prompts or completions
persist beyond the active request except Hermes's local FTS5 memory under
~/.hermes/ (operator-local, never leaves the host).

EU-RESIDENCY CAVEAT: Hermes can OPTIONALLY delegate to the Anthropic API
(US) or the Claude Code CLI when the operator sets hermes_anthropic_api_key
/ hermes_claude_code_enabled. Both are OFF by default (all-local Ollama). If
the operator enables Anthropic delegation, prompts may be transferred to
Anthropic (US) — update transfers_outside_eu + processors accordingly.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`
- **Data categories:** `operator_prompts`; `agent_run_metadata`; `agent_memory`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** transient (not persisted)
- **Storage:** host service (non-Docker / launchd)
- **Security measures:** platform baseline (see above)

#### Loop — `svc_loop`
- **Purpose:** The agentic-loop cadence runs three scheduled maintenance ceremonies on
the operator's own repository: proposing a bounded code change against a
reported weakness, opening a reviewed merge request for judged changes,
and merging behind deterministic gates. It processes repository content
and operator-authored weakness records (legitimate interest in service
operation and security remediation, Art. 6(1)(f)). The paused `propose`
job, when the operator unpauses it, sends repository excerpts and
weakness titles to the model backend the estate has configured for the
claude CLI — the same transfer the attended ceremony performs today.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`
- **Data categories:** `repository_content`; `job_metadata`
- **Recipients / processors:** `Anthropic (US) — claude CLI backend, authoring proposals when the propose job runs`
- **Transfers outside EU:** **Yes**
- **Retention:** indefinite (lifecycle-managed; deletion via DSAR)
- **Storage:** host service (non-Docker / launchd)
- **Security measures:** platform baseline (see above)

#### Npm Supply Chain — `svc_npm-supply-chain`
- **Purpose:** Supply-chain integrity checking of installed npm dependencies
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`
- **Data categories:** `software_inventory`
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
- **Data categories:** `operator_prompts`; `agent_run_metadata`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** transient (not persisted)
- **Storage:** host service (non-Docker / launchd)
- **Security measures:** platform baseline (see above)

#### Pulse — `svc_pulse`
- **Purpose:** Pulse is the host-side scheduled-job runner. It processes aggregated job
catalog metadata (plugin name, job name, schedule, command) authored or
triggered by the operator, in order to schedule and run maintenance jobs
(legitimate interest in service operation, Art. 6(1)(f)). Only the
operator authors or triggers jobs; no tenant end-user data is processed.
- **Legal basis (Art. 6):** `legitimate_interests`
- **Data subjects:** `operators`
- **Data categories:** `aggregated_job_metadata`
- **Recipients / processors:** —
- **Transfers outside EU:** No
- **Retention:** indefinite (lifecycle-managed; deletion via DSAR)
- **Storage:** host service (non-Docker / launchd)
- **Security measures:** platform baseline (see above)
