# ONLYOFFICE Document Server

> Collaborative office-editor **backend** (DOCX/XLSX/PPTX). Embedded and driven by host apps (Nextcloud, BookStack, Outline) over a shared JWT secret — end-users never log in here directly. b2b compose stack.

## Quick Reference

| | |
|---|---|
| **System id** | `nos.b2b.onlyoffice` |
| **Domain** | `office.{{ tenant_domain }}` (default `tenant_domain: dev.local`; optional host-alias segment prepended) |
| **Host port** | `3015` → container `:80` (bound `127.0.0.1` unless `services_lan_access: true`) |
| **Stack** | `b2b` |
| **Toggle** | `install_onlyoffice` |
| **Image** | `onlyoffice/documentserver:9.3.1.2` (via `onlyoffice_image` / `onlyoffice_version`; the euro-office fork `ghcr.io/euro-office/documentserver` is a JWT-compatible flip) |
| **Service alias** | `onlyoffice` (`onlyoffice_service_name` — the docker-network name host apps resolve as `http://onlyoffice/`) |
| **Mem / CPU** | `onlyoffice_mem_limit` (default `2g`, critical class) / `onlyoffice_cpus` (default `1.0`) |

### Data paths (`nos_data_root` default `~/nos`)

| Host path | Container mount |
|---|---|
| `{{ nos_data_root }}/platform/services/onlyoffice/data` | `/var/www/onlyoffice/Data` |
| `{{ nos_data_root }}/platform/services/onlyoffice/logs` | `/var/log/onlyoffice` |
| `{{ nos_data_root }}/platform/services/onlyoffice/lib` | `/var/lib/onlyoffice` |
| `{{ nos_data_root }}/platform/services/onlyoffice/db` (`onlyoffice_db_dir`) | `/var/lib/postgresql` (image-embedded PostgreSQL) |

The embedded PostgreSQL holds only transient document-server state; the real documents live in the host apps. Because the cluster is baked into the image layers, the `db` mount cannot be initdb'd from empty — see the euro-office switch procedure in `roles/pazny.onlyoffice/defaults/main.yml`.

## Authentication

- **SSO bucket:** `forward_auth` (Authentik `authentik@file` middleware). RBAC tier **3** (user).
- **Two-layer model:** the Authentik forward-auth gate protects only the **UI** part (`/welcome`, admin). The **API** endpoints (`/healthcheck`, document conversion, command service) are reachable **without** Authentik and are secured by **JWT signing** instead.
- **JWT:** `onlyoffice_jwt_enabled: true`, header `Authorization`, `JWT_IN_BODY: true`. The secret `onlyoffice_jwt_secret` (`default.credentials.yml`, auto-generated on removal-reset) MUST be shared with every host app that embeds the editor. There is no per-user login and no admin account here.

## Health Check

- **Endpoint:** `GET /healthcheck`
- **Expected:** `200 OK` returning `true` (container healthcheck: `curl -f http://127.0.0.1/healthcheck`). Unauthenticated — it is not behind the forward-auth gate.

## Dependencies

- **Consumers:** Nextcloud, BookStack, Outline — embed the editor via iframe + shared JWT (the Nextcloud role derives `onlyoffice_internal_url` from `onlyoffice_service_name`).
- **Redis:** optional — throughput boost when `install_redis: true` (`REDIS_SERVER_HOST: redis`).
- **Authentik:** optional — forward-auth gate on the UI only.
- No external database dependency — PostgreSQL is embedded in the image.

> Note: ONLYOFFICE (live-document editing) and Documenso (e-signature) are independent, non-competing services. The euro-office pilot only swaps the editing backend; it has no e-signing surface, so Documenso stays.

## Upgrades

- Version pin lives in `onlyoffice_version` (`roles/pazny.onlyoffice/defaults/main.yml`) and `default.config.yml`. Image/version and the euro-office `onlyoffice_image` flip are kept separate on purpose.
