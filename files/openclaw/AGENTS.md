# Sub-agenti – konfigurace a odpovědnosti

Tento soubor definuje specializované sub-agenty, které **Inspektor Klepítko**
(DevOps Lead) může aktivovat pro konkrétní úkoly.

Každý agent komunikuje se systémy výhradně přes API jako `openclaw-bot`
service account. CLI/sudo přístup jen když API neexistuje.

Detailní skills pro každý systém: `systems/<slug>/SKILLS.md` (symlink do `docs/systems/`)

---

## GrafanaAgent

**Specializace:** Observability — metriky, logy, traces, alerty

**Systémy:** Grafana, Prometheus, Loki, Tempo

**Kontext:**
- Grafana API: `https://grafana.dev.local/api/`
- Auth: Service Account Bearer token (`~/agents/tokens/grafana.token`)
- Datasources: Prometheus (PromQL), Loki (LogQL), Tempo (TraceQL)
- Dashboardy: `~/observability/dashboards/`
- Skills: [systems/grafana/SKILLS.md](systems/grafana/SKILLS.md)

**Aktivace:**
```
Deleguj na GrafanaAgent: Zkontroluj nginx 5xx errory za poslední hodinu v Loki
```

---

## DevOpsAgent

**Specializace:** Git repozitáře, CI/CD pipelines, kód

**Systémy:** Gitea, Woodpecker CI

**Kontext:**
- Gitea API: `https://git.dev.local/api/v1/`
- Auth: Bearer token (`~/agents/tokens/gitea.token`)
- SSH: `git@localhost:2222`
- CI: Woodpecker (Gitea OAuth trigger)
- Skills: [systems/gitea/SKILLS.md](systems/gitea/SKILLS.md)

**Aktivace:**
```
Deleguj na DevOpsAgent: Vytvoř repozitář pro projekt [název] a nastav webhook
```

---

## HomeAgent

**Specializace:** Domácí automatizace — zařízení, scény, automatizace

**Systémy:** Home Assistant

**Kontext:**
- HA API: `https://home.dev.local/api/`
- Auth: Long-Lived Access Token (`~/agents/tokens/home-assistant.token`)
- WebSocket: `wss://home.dev.local/api/websocket`
- Skills: [systems/home-assistant/SKILLS.md](systems/home-assistant/SKILLS.md)

**Aktivace:**
```
Deleguj na HomeAgent: Zapni osvětlení v obýváku a nastav jas na 80%
```

---

## StorageAgent

**Specializace:** Souborový management — cloud + S3 object storage

**Systémy:** Nextcloud (WebDAV/OCS), RustFS (S3)

**Kontext:**
- Nextcloud: `https://cloud.dev.local/remote.php/dav/` (WebDAV)
- RustFS S3: `https://s3.dev.local` (AWS Signature V4)
- Auth: App Password / AWS keys (`~/agents/tokens/`)
- Skills: [systems/nextcloud/SKILLS.md](systems/nextcloud/SKILLS.md), [systems/rustfs/SKILLS.md](systems/rustfs/SKILLS.md)

**Aktivace:**
```
Deleguj na StorageAgent: Nahraj zálohu do S3 bucketu backups/
```

---

## WorkflowAgent

**Specializace:** Automatizace workflow — integrace, webhooky, orchestrace

**Systémy:** n8n

**Kontext:**
- n8n API: `https://n8n.dev.local/api/v1/`
- Auth: API Key header (`~/agents/tokens/n8n.token`)
- Skills: [systems/n8n/SKILLS.md](systems/n8n/SKILLS.md)

**Aktivace:**
```
Deleguj na WorkflowAgent: Spusť workflow "denní report" a vrať výsledky
```

---

## DataAgent

**Specializace:** Business data, BI dotazy, databáze, zálohy

**Systémy:** Metabase, Superset, ERPNext, PostgreSQL, MariaDB, Redis

**Kontext:**
- Metabase API: `https://bi.dev.local/api/` (Session token)
- Superset API: `https://superset.dev.local/api/v1/` (JWT)
- ERPNext API: `https://erp.dev.local/api/resource/` (API key)
- DB přístup: `docker exec` pro psql/mysql jen jako fallback
- Skills: [systems/metabase/SKILLS.md](systems/metabase/SKILLS.md), [systems/erpnext/SKILLS.md](systems/erpnext/SKILLS.md), [systems/superset/SKILLS.md](systems/superset/SKILLS.md)

**Aktivace:**
```
Deleguj na DataAgent: Spusť SQL dotaz na počet objednávek za poslední měsíc
```

---

## SecurityAgent

**Specializace:** IAM, secrets, hesla, audit

**Systémy:** Authentik (SSO), Infisical (secrets vault), Vaultwarden (password vault)

**Kontext:**
- Authentik API: `https://auth.dev.local/api/v3/` (Bearer token)
- Infisical API: `https://vault.dev.local/api/v1/` (Service token)
- Vaultwarden API: `https://pass.dev.local/api/` (Bearer token, read-only!)
- Skills: [systems/authentik/SKILLS.md](systems/authentik/SKILLS.md), [systems/infisical/SKILLS.md](systems/infisical/SKILLS.md), [systems/vaultwarden/SKILLS.md](systems/vaultwarden/SKILLS.md)

**Aktivace:**
```
Deleguj na SecurityAgent: Zkontroluj kdo se přihlásil za posledních 24 hodin v Authentiku
```

---

## ContentAgent

**Specializace:** Knowledge base, wiki, CMS, média, e-booky, offline obsah

**Systémy:** Outline, WordPress, Jellyfin, Calibre-Web, Kiwix

**Kontext:**
- Outline API: `https://wiki.dev.local/api/` (Bearer token)
- WordPress REST: `https://wp.dev.local/wp-json/wp/v2/` (Application Password)
- Jellyfin API: `https://media.dev.local/` (API key)
- Calibre-Web: CLI pouze (docker exec)
- Kiwix: `https://kiwix.dev.local/search` (bez auth)
- Skills: [systems/outline/SKILLS.md](systems/outline/SKILLS.md), [systems/wordpress/SKILLS.md](systems/wordpress/SKILLS.md), [systems/jellyfin/SKILLS.md](systems/jellyfin/SKILLS.md)

**Aktivace:**
```
Deleguj na ContentAgent: Najdi v wiki dokumentaci k autentizaci a vrať obsah
```

---

## CommAgent

**Specializace:** Komunikace, sociální sítě, federace

**Systémy:** Bluesky PDS (AT Protocol)

**Kontext:**
- Bluesky XRPC: `https://pds.dev.local/xrpc/` (Bearer JWT)
- AT Protocol: decentralizovaná sociální síť
- Skills: [systems/bluesky-pds/SKILLS.md](systems/bluesky-pds/SKILLS.md)

**Aktivace:**
```
Deleguj na CommAgent: Publikuj status update na Bluesky
```

---

## MonitorAgent

**Specializace:** Uptime monitoring, incidenty, status page

**Systémy:** Uptime Kuma, Portainer

**Kontext:**
- Uptime Kuma: `https://uptime.dev.local/` (WebSocket + REST API)
- Portainer: `https://portainer.dev.local/api/` (JWT)
- Skills: [systems/uptime-kuma/SKILLS.md](systems/uptime-kuma/SKILLS.md), [systems/portainer/SKILLS.md](systems/portainer/SKILLS.md)

**Aktivace:**
```
Deleguj na MonitorAgent: Které služby jsou aktuálně down?
```

---

## Workflow delegování

```
Inspektor Klepítko (DevOps Lead)
│
├── Přijme úkol
├── Vytvoří log soubor v ~/agents/log/
├── Rozdělí na sub-úkoly, vybere vhodného agenta
│
├──► GrafanaAgent   (observability: metriky, logy, traces)
├──► DevOpsAgent    (git, CI/CD, kód)
├──► HomeAgent      (home automation, IoT)
├──► StorageAgent   (soubory: cloud + S3)
├──► WorkflowAgent  (automatizace: n8n)
├──► DataAgent      (BI, ERP, databáze)
├──► SecurityAgent  (SSO, secrets, audit)
├──► ContentAgent   (wiki, CMS, média, knihy)
├──► CommAgent      (sociální sítě, federace)
└──► MonitorAgent   (uptime, kontejnery)
     │
     └── Každý agent komunikuje se systémy přes API
         jako openclaw-bot service account
         Tokeny: ~/agents/tokens/<system>.token
```
