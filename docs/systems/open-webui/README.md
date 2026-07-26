# Open WebUI

> Chat UI for local Ollama models. Multi-user, RAG, model management. All state
> (users, chats, knowledge bases) lives in one SQLite file, `webui.db`, under the
> bind-mounted `/app/backend/data`.

## Quick Reference

| | |
|---|---|
| **URL** | `https://ai{host_alias_seg}.{tenant_domain}` (default `https://ai.dev.local`) |
| **Port** | `3004` (`openwebui_port`; loopback publish `127.0.0.1:3004` → container `8080`. `services_lan_access: true` publishes on all interfaces instead) |
| **Stack** | `iiab` |
| **Node id** | `nos.iiab.open-webui` |
| **Toggle** | `install_openwebui: true` |
| **Image** | `ghcr.io/open-webui/open-webui:0.9.6` (`openwebui_version`) |
| **Data** | `{{ nos_data_root }}/platform/services/openwebui/data` → `/app/backend/data` (default `~/nos/platform/services/openwebui/data`; external-storage override → `{{ external_storage_root }}/openwebui`) — holds `webui.db` |
| **Compose** | `~/stacks/iiab/docker-compose.yml` + `~/stacks/iiab/overrides/open-webui.yml` (+ `open-webui-base.yml` from the plugin) |
| **Container** | `iiab-open-webui-1` (compose service `open-webui`) |
| **Memory limit** | `2g` (`docker_mem_limit_critical`) |
| **Networks** | `iiab_net` + the shared stacks network (`shared_net`), plus `extra_hosts` for `host.docker.internal` |

`openwebui_domain`, `openwebui_port`, `openwebui_version`, `openwebui_data_dir` and the admin
credentials pin in `default.config.yml` / `default.credentials.yml`; role defaults are fallbacks.
`~/stacks/iiab/` still holds the compose files — only the data row moved to `nos_data_root`.

## Authentication

- **Admin user:** `{{ default_admin_email }}` → `admin@dev.local` on the default tenant
  (`openwebui_admin_email`).
- **Admin password:** `{global_password_prefix}_pw_openwebui_admin`
  (`openwebui_admin_password`). `roles/pazny.open_webui/tasks/post.yml` seeds this admin **directly into `webui.db`** on an
  empty DB and reconverges the bcrypt hash on later runs — it never POSTs the public signup endpoint.
- **Local signup:** OFF. `openwebui_enable_signup: false` in `default.config.yml` shadows the role
  default `true`; the public `/auth/signup` page used to let anyone self-register, and the FIRST
  registrant becomes admin — a public first-admin race during a blank run.
- **SSO:** `native_oidc` (plugin `open-webui-base`, tier 3 = user). Env-driven, rendered by the
  plugin compose-extension when `install_authentik` is true.
  - Authentik client `nos-openwebui`, slug `open-webui`
  - Redirect URI: `https://{openwebui_domain}/oauth/oidc/callback`
  - Discovery: `https://{authentik_domain}/application/o/open-webui/.well-known/openid-configuration`
  - `OAUTH_MERGE_ACCOUNTS_BY_EMAIL=true` — the seeded admin and the Authentik admin share an email,
    so the first OIDC login merges into it and the seeded password stays as break-glass.
  - `ENABLE_OAUTH_ROLE_MANAGEMENT=true` with `OAUTH_ROLES_CLAIM=groups`: tier-1 Authentik groups map
    to WebUI admin, tier-3 groups to allowed users — both derived from `authentik_rbac_tiers`.
  - On a local TLD the extension also mounts the mkcert root CA and sets `REQUESTS_CA_BUNDLE` /
    `SSL_CERT_FILE`; on a public TLD it must not (the system trust store validates LE).

## API Access

- **Base URL:** `https://ai{host_alias_seg}.{tenant_domain}/api/`
- **Auth method:** Bearer JWT, obtained from `POST /api/v1/auths/signin`.
- **Bot account:** none. The playbook provisions **no** service account and **no** token file —
  `openclaw-bot` and `~/agents/tokens/open-webui.token` were `docs/systems/TEMPLATE/` boilerplate that
  nothing in the repo ever creates. Sign in as the seeded admin, or create a dedicated user in the UI.

## Hardening (rendered into the compose env)

- `CODE_INTERPRETER_ENGINE=pyodide` — pinned so a config merge can never flip to `jupyter`, whose
  import block is escapable via a leaked `_real_import` reference (REM-054).
- `CHAT_RESPONSE_MAX_TOOL_CALL_RETRIES=5` (`openwebui_max_tool_call_retries`) — caps multi-hop
  prompt injection through re-injected tool results (REM-055); upstream default is 30.
- Telemetry off: `SCARF_NO_ANALYTICS`, `DO_NOT_TRACK`, `ANONYMIZED_TELEMETRY`.

## Health Check

- **Endpoint:** `GET /api/config`
- **Expected:** `200 OK`
- Used by the container healthcheck (`curl -sf http://localhost:8080/api/config`), the plugin's
  `post_compose` wait, and `post.yml`'s hard-failing API wait.

## Dependencies

- Ollama on the **host**, reached at `http://host.docker.internal:11434` (`OLLAMA_BASE_URL`).
- Authentik (native OIDC; optional — without it the seeded local admin is the only way in).
- MCP Gateway (`mcpo`) — optional. When `install_mcp_gateway` is true the compose template registers
  `http://mcpo:8000` as a bearer-authed tool server via `TOOL_SERVER_CONNECTIONS`.
- No external database — SQLite `webui.db` in the data mount.
