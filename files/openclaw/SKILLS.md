# OpenClaw — Agregovaný registr skills

> Přehled všech dostupných skills napříč systémy devBoxNOS.
> Detaily: `systems/<slug>/SKILLS.md`

## Princip

- **API-first**: Všechny skills používají REST/WebSocket API jako `openclaw-bot`
- **CLI fallback**: Pouze když API neexistuje (occ, artisan, psql)
- **Tokeny**: `~/agents/tokens/<system>.token`
- **Rotace**: Auto-generated při `blank=true` run, rotace přes Infisical

---

## GrafanaAgent

| Skill | Endpoint | Popis |
|-------|----------|-------|
| query-prometheus | `POST /api/ds/query` | PromQL dotaz na metriky |
| query-loki | `POST /api/ds/query` | LogQL dotaz na logy |
| query-tempo | `POST /api/ds/query` | TraceQL dotaz na traces |
| list-dashboards | `GET /api/search` | Seznam dashboardů |
| create-alert-rule | `POST /api/v1/provisioning/alert-rules` | Nový alert |
| check-datasource-health | `GET /api/datasources/uid/*/health` | Stav datasource |

## DevOpsAgent

| Skill | Endpoint | Popis |
|-------|----------|-------|
| list-repos | `GET /api/v1/repos/search` | Seznam repozitářů |
| create-repo | `POST /api/v1/user/repos` | Nový repozitář |
| list-issues | `GET /api/v1/repos/{o}/{r}/issues` | Issues v repo |
| create-pull-request | `POST /api/v1/repos/{o}/{r}/pulls` | Nový PR |
| manage-webhooks | `POST /api/v1/repos/{o}/{r}/hooks` | Webhook CRUD |

## HomeAgent

| Skill | Endpoint | Popis |
|-------|----------|-------|
| get-states | `GET /api/states/{entity_id}` | Stav zařízení |
| call-service | `POST /api/services/{domain}/{service}` | Ovládání zařízení |
| trigger-automation | `POST /api/services/automation/trigger` | Spuštění automatizace |
| activate-scene | `POST /api/services/scene/turn_on` | Aktivace scény |
| get-history | `GET /api/history/period/{ts}` | Historie stavů |

## StorageAgent

| Skill | Endpoint | Popis |
|-------|----------|-------|
| upload-file | `PUT /remote.php/dav/files/...` | Upload do Nextcloud |
| download-file | `GET /remote.php/dav/files/...` | Download z Nextcloud |
| create-share | `POST /ocs/.../shares` | Sdílení souboru |
| create-bucket | `aws s3 mb s3://...` | Nový S3 bucket |
| upload-object | `aws s3 cp ... s3://...` | Upload do S3 |
| presign-url | `aws s3 presign ...` | Dočasný download link |

## WorkflowAgent

| Skill | Endpoint | Popis |
|-------|----------|-------|
| list-workflows | `GET /api/v1/workflows` | Seznam workflow |
| execute-workflow | `POST /api/v1/workflows/{id}/execute` | Spuštění workflow |
| list-executions | `GET /api/v1/executions` | Historie běhů |
| activate-workflow | `PATCH /api/v1/workflows/{id}` | Aktivace/deaktivace |

## DataAgent

| Skill | Endpoint | Popis |
|-------|----------|-------|
| run-query | `POST /api/dataset` (Metabase) | SQL dotaz |
| run-saved-question | `POST /api/card/{id}/query` | Uložený report |
| list-documents | `GET /api/resource/{doctype}` (ERPNext) | Business data |
| execute-query | `POST /api/v1/sqllab/execute` (Superset) | SQL Lab |

## SecurityAgent

| Skill | Endpoint | Popis |
|-------|----------|-------|
| list-users | `GET /api/v3/core/users/` (Authentik) | Seznam uživatelů SSO |
| get-events | `GET /api/v3/events/events/` | Audit log |
| get-secret | `GET /api/v1/secrets/{name}` (Infisical) | Čtení secretu |
| create-secret | `POST /api/v1/secrets/{name}` | Nový secret |

## ContentAgent

| Skill | Endpoint | Popis |
|-------|----------|-------|
| search-documents | `POST /api/documents.search` (Outline) | Hledání ve wiki |
| create-document | `POST /api/documents.create` | Nová wiki stránka |
| list-posts | `GET /wp-json/wp/v2/posts` (WordPress) | Blog příspěvky |
| search-media | `GET /Items?searchTerm=...` (Jellyfin) | Hledání médií |
| search-content | `GET /search?pattern=...` (Kiwix) | Offline obsah |

## CommAgent

| Skill | Endpoint | Popis |
|-------|----------|-------|
| create-post | `POST /xrpc/com.atproto.repo.createRecord` | Bluesky post |
| get-profile | `GET /xrpc/app.bsky.actor.getProfile` | AT Protocol profil |

## MonitorAgent

| Skill | Endpoint | Popis |
|-------|----------|-------|
| list-monitors | `GET /api/monitors` (Uptime Kuma) | Seznam monitorů |
| get-status | `GET /api/status-page/...` | Status page |
| list-containers | `GET /api/endpoints/1/docker/containers/json` (Portainer) | Docker stav |
| container-logs | `GET /api/endpoints/1/docker/containers/{id}/logs` | Logy kontejneru |
