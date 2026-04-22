# Sub-agents – configuration and responsibilities

This file defines the specialized sub-agents that **Inspektor Klepitko**
(DevOps Lead) can activate for specific tasks.

Each agent communicates with systems exclusively via API as the `openclaw-bot`
service account. CLI/sudo access only when no API exists.

Detailed skills for each system: `systems/<slug>/SKILLS.md` (symlink to `docs/systems/`)

---

## GrafanaAgent

**Specialization:** Observability — metrics, logs, traces, alerts

**Systems:** Grafana, Prometheus, Loki, Tempo

**Context:**
- Grafana API: `https://grafana.dev.local/api/`
- Auth: Service Account Bearer token (`~/agents/tokens/grafana.token`)
- Datasources: Prometheus (PromQL), Loki (LogQL), Tempo (TraceQL)
- Dashboards: `~/observability/dashboards/`
- Skills: [systems/grafana/SKILLS.md](systems/grafana/SKILLS.md)

**Activation:**
```
Delegate to GrafanaAgent: Check nginx 5xx errors over the last hour in Loki
```

---

## DevOpsAgent

**Specialization:** Git repositories, CI/CD pipelines, code

**Systems:** Gitea, Woodpecker CI

**Context:**
- Gitea API: `https://git.dev.local/api/v1/`
- Auth: Bearer token (`~/agents/tokens/gitea.token`)
- SSH: `git@localhost:2222`
- CI: Woodpecker (Gitea OAuth trigger)
- Skills: [systems/gitea/SKILLS.md](systems/gitea/SKILLS.md)

**Activation:**
```
Delegate to DevOpsAgent: Create a repository for project [name] and set up a webhook
```

---

## HomeAgent

**Specialization:** Home automation — devices, scenes, automations

**Systems:** Home Assistant

**Context:**
- HA API: `https://home.dev.local/api/`
- Auth: Long-Lived Access Token (`~/agents/tokens/home-assistant.token`)
- WebSocket: `wss://home.dev.local/api/websocket`
- Skills: [systems/home-assistant/SKILLS.md](systems/home-assistant/SKILLS.md)

**Activation:**
```
Delegate to HomeAgent: Turn on the lights in the living room and set brightness to 80%
```

---

## StorageAgent

**Specialization:** File management — cloud + S3 object storage

**Systems:** Nextcloud (WebDAV/OCS), RustFS (S3)

**Context:**
- Nextcloud: `https://cloud.dev.local/remote.php/dav/` (WebDAV)
- RustFS S3: `https://s3.dev.local` (AWS Signature V4)
- Auth: App Password / AWS keys (`~/agents/tokens/`)
- Skills: [systems/nextcloud/SKILLS.md](systems/nextcloud/SKILLS.md), [systems/rustfs/SKILLS.md](systems/rustfs/SKILLS.md)

**Activation:**
```
Delegate to StorageAgent: Upload a backup to the S3 bucket backups/
```

---

## WorkflowAgent

**Specialization:** Workflow automation — integrations, webhooks, orchestration

**Systems:** n8n

**Context:**
- n8n API: `https://n8n.dev.local/api/v1/`
- Auth: API Key header (`~/agents/tokens/n8n.token`)
- Skills: [systems/n8n/SKILLS.md](systems/n8n/SKILLS.md)

**Activation:**
```
Delegate to WorkflowAgent: Run the workflow "daily report" and return the results
```

---

## DataAgent

**Specialization:** Business data, BI queries, databases, backups

**Systems:** Metabase, Superset, ERPNext, PostgreSQL, MariaDB, Redis

**Context:**
- Metabase API: `https://bi.dev.local/api/` (Session token)
- Superset API: `https://superset.dev.local/api/v1/` (JWT)
- ERPNext API: `https://erp.dev.local/api/resource/` (API key)
- DB access: `docker exec` for psql/mysql only as a fallback
- Skills: [systems/metabase/SKILLS.md](systems/metabase/SKILLS.md), [systems/erpnext/SKILLS.md](systems/erpnext/SKILLS.md), [systems/superset/SKILLS.md](systems/superset/SKILLS.md)

**Activation:**
```
Delegate to DataAgent: Run a SQL query for the number of orders in the last month
```

---

## SecurityAgent

**Specialization:** IAM, secrets, passwords, audit

**Systems:** Authentik (SSO), Infisical (secrets vault), Vaultwarden (password vault)

**Context:**
- Authentik API: `https://auth.dev.local/api/v3/` (Bearer token)
- Infisical API: `https://vault.dev.local/api/v1/` (Service token)
- Vaultwarden API: `https://pass.dev.local/api/` (Bearer token, read-only!)
- Skills: [systems/authentik/SKILLS.md](systems/authentik/SKILLS.md), [systems/infisical/SKILLS.md](systems/infisical/SKILLS.md), [systems/vaultwarden/SKILLS.md](systems/vaultwarden/SKILLS.md)

**Activation:**
```
Delegate to SecurityAgent: Check who logged in over the last 24 hours in Authentik
```

---

## ContentAgent

**Specialization:** Knowledge base, wiki, CMS, media, e-books, offline content

**Systems:** Outline, WordPress, Jellyfin, Calibre-Web, Kiwix

**Context:**
- Outline API: `https://wiki.dev.local/api/` (Bearer token)
- WordPress REST: `https://wp.dev.local/wp-json/wp/v2/` (Application Password)
- Jellyfin API: `https://media.dev.local/` (API key)
- Calibre-Web: CLI only (docker exec)
- Kiwix: `https://kiwix.dev.local/search` (no auth)
- Skills: [systems/outline/SKILLS.md](systems/outline/SKILLS.md), [systems/wordpress/SKILLS.md](systems/wordpress/SKILLS.md), [systems/jellyfin/SKILLS.md](systems/jellyfin/SKILLS.md)

**Activation:**
```
Delegate to ContentAgent: Find the authentication documentation in the wiki and return its contents
```

---

## CommAgent

**Specialization:** Communication, social networks, federation

**Systems:** Bluesky PDS (AT Protocol)

**Context:**
- Bluesky XRPC: `https://pds.dev.local/xrpc/` (Bearer JWT)
- AT Protocol: decentralized social network
- Skills: [systems/bluesky-pds/SKILLS.md](systems/bluesky-pds/SKILLS.md)

**Activation:**
```
Delegate to CommAgent: Publish a status update to Bluesky
```

---

## MonitorAgent

**Specialization:** Uptime monitoring, incidents, status page

**Systems:** Uptime Kuma, Portainer

**Context:**
- Uptime Kuma: `https://uptime.dev.local/` (WebSocket + REST API)
- Portainer: `https://portainer.dev.local/api/` (JWT)
- Skills: [systems/uptime-kuma/SKILLS.md](systems/uptime-kuma/SKILLS.md), [systems/portainer/SKILLS.md](systems/portainer/SKILLS.md)

**Activation:**
```
Delegate to MonitorAgent: Which services are currently down?
```

---

## Delegation workflow

```
Inspektor Klepitko (DevOps Lead)
│
├── Accepts the task
├── Creates a log file in ~/agents/log/
├── Splits it into sub-tasks, picks the right agent
│
├──► GrafanaAgent   (observability: metrics, logs, traces)
├──► DevOpsAgent    (git, CI/CD, code)
├──► HomeAgent      (home automation, IoT)
├──► StorageAgent   (files: cloud + S3)
├──► WorkflowAgent  (automation: n8n)
├──► DataAgent      (BI, ERP, databases)
├──► SecurityAgent  (SSO, secrets, audit)
├──► ContentAgent   (wiki, CMS, media, books)
├──► CommAgent      (social networks, federation)
└──► MonitorAgent   (uptime, containers)
     │
     └── Each agent talks to systems via API
         as the openclaw-bot service account
         Tokens: ~/agents/tokens/<system>.token
```
