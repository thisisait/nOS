# OpenClaw — Aggregated skill registry

> Overview of all skills available across nOS systems.
> Details: `systems/<slug>/SKILLS.md`

## Principle

- **API-first**: All skills use REST/WebSocket APIs as `openclaw-bot`
- **CLI fallback**: Only when no API exists (occ, artisan, psql)
- **Tokens**: `~/agents/tokens/<system>.token`
- **Rotation**: Auto-generated on a `blank=true` run, rotation via Infisical

---

## GrafanaAgent

| Skill | Endpoint | Description |
|-------|----------|-------------|
| query-prometheus | `POST /api/ds/query` | PromQL query for metrics |
| query-loki | `POST /api/ds/query` | LogQL query for logs |
| query-tempo | `POST /api/ds/query` | TraceQL query for traces |
| list-dashboards | `GET /api/search` | List of dashboards |
| create-alert-rule | `POST /api/v1/provisioning/alert-rules` | New alert |
| check-datasource-health | `GET /api/datasources/uid/*/health` | Datasource health |

## DevOpsAgent

| Skill | Endpoint | Description |
|-------|----------|-------------|
| list-repos | `GET /api/v1/repos/search` | List of repositories |
| create-repo | `POST /api/v1/user/repos` | New repository |
| list-issues | `GET /api/v1/repos/{o}/{r}/issues` | Issues in a repo |
| create-pull-request | `POST /api/v1/repos/{o}/{r}/pulls` | New PR |
| manage-webhooks | `POST /api/v1/repos/{o}/{r}/hooks` | Webhook CRUD |

## HomeAgent

| Skill | Endpoint | Description |
|-------|----------|-------------|
| get-states | `GET /api/states/{entity_id}` | Device state |
| call-service | `POST /api/services/{domain}/{service}` | Device control |
| trigger-automation | `POST /api/services/automation/trigger` | Trigger an automation |
| activate-scene | `POST /api/services/scene/turn_on` | Activate a scene |
| get-history | `GET /api/history/period/{ts}` | State history |

## StorageAgent

| Skill | Endpoint | Description |
|-------|----------|-------------|
| upload-file | `PUT /remote.php/dav/files/...` | Upload to Nextcloud |
| download-file | `GET /remote.php/dav/files/...` | Download from Nextcloud |
| create-share | `POST /ocs/.../shares` | File sharing |
| create-bucket | `aws s3 mb s3://...` | New S3 bucket |
| upload-object | `aws s3 cp ... s3://...` | Upload to S3 |
| presign-url | `aws s3 presign ...` | Temporary download link |

## WorkflowAgent

| Skill | Endpoint | Description |
|-------|----------|-------------|
| list-workflows | `GET /api/v1/workflows` | List of workflows |
| execute-workflow | `POST /api/v1/workflows/{id}/execute` | Execute a workflow |
| list-executions | `GET /api/v1/executions` | Run history |
| activate-workflow | `PATCH /api/v1/workflows/{id}` | Activate/deactivate |

## DataAgent

| Skill | Endpoint | Description |
|-------|----------|-------------|
| run-query | `POST /api/dataset` (Metabase) | SQL query |
| run-saved-question | `POST /api/card/{id}/query` | Saved report |
| list-documents | `GET /api/resource/{doctype}` (ERPNext) | Business data |
| execute-query | `POST /api/v1/sqllab/execute` (Superset) | SQL Lab |

## SecurityAgent

| Skill | Endpoint | Description |
|-------|----------|-------------|
| list-users | `GET /api/v3/core/users/` (Authentik) | List of SSO users |
| get-events | `GET /api/v3/events/events/` | Audit log |
| get-secret | `GET /api/v1/secrets/{name}` (Infisical) | Read a secret |
| create-secret | `POST /api/v1/secrets/{name}` | New secret |

## ContentAgent

| Skill | Endpoint | Description |
|-------|----------|-------------|
| search-documents | `POST /api/documents.search` (Outline) | Search the wiki |
| create-document | `POST /api/documents.create` | New wiki page |
| list-posts | `GET /wp-json/wp/v2/posts` (WordPress) | Blog posts |
| search-media | `GET /Items?searchTerm=...` (Jellyfin) | Search media |
| search-content | `GET /search?pattern=...` (Kiwix) | Offline content |

## CommAgent

| Skill | Endpoint | Description |
|-------|----------|-------------|
| create-post | `POST /xrpc/com.atproto.repo.createRecord` | Bluesky post |
| get-profile | `GET /xrpc/app.bsky.actor.getProfile` | AT Protocol profile |

## MonitorAgent

| Skill | Endpoint | Description |
|-------|----------|-------------|
| list-monitors | `GET /api/monitors` (Uptime Kuma) | List of monitors |
| get-status | `GET /api/status-page/...` | Status page |
| list-containers | `GET /api/endpoints/1/docker/containers/json` (Portainer) | Docker status |
| container-logs | `GET /api/endpoints/1/docker/containers/{id}/logs` | Container logs |
