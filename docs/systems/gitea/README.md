# Gitea

> Self-hosted Git server. Repozitare, issues, pull requesty, webhooky.

## Quick Reference

| | |
|---|---|
| **URL** | `https://git{host_alias_seg}.{tenant_domain}` (default `https://git.dev.local`) |
| **Port** | `3003` (`gitea_port`; loopback publish `127.0.0.1:3003` → container `3000`) |
| **SSH** | `localhost:2222` (`gitea_ssh_port`; always loopback-bound → container `22`) |
| **Stack** | `devops` |
| **Toggle** | `install_gitea: true` (default `true`) |
| **Compose** | `~/stacks/devops/docker-compose.yml` (role fragment: `~/stacks/devops/overrides/gitea.yml`) |
| **Image** | `gitea/gitea:1.26.4` (`gitea_version`) |
| **Data** | `{{ nos_data_root }}/platform/services/gitea/data` (default `~/nos/platform/services/gitea/data`) → `/data` |
| **Mem / CPU** | `gitea_mem_limit` (default `1g`) / `1.0` |

`nos_data_root` defaults to `~/nos` (`{{ HOME }}/nos`); `tasks/stacks/external-paths.yml`
relocates `gitea_data_dir` to `{{ external_storage_root }}/gitea` when external storage is
in play. The SQLite database, repositories, and LFS all live under that one `/data` mount.
The pinned version is exactly `1.26.4` — 1.25.x went EOL (REM-099) and 1.26.3 carried a
regression.

## Authentication

- **Admin user:** `gitea_admin_user`, default `{{ ansible_facts['user_id'] }}` (the system username)
- **Admin password:** `{global_password_prefix}_pw_gitea` (`gitea_admin_password`)
- **SSO:** `native_oidc` (Authentik OAuth2 client `nos-gitea`, slug `gitea`), RBAC tier **2**.
  - Redirect URI: `https://{gitea_domain}/user/oauth2/authentik/callback`
  - Scopes: `openid`, `email`, `profile`
  - Registered as an OAuth source through the `/api/v1/admin/identity-providers` Admin API;
    surfaces a "Sign in with Authentik" button on Gitea's login page.
- **Local signup is off, OIDC auto-create is on:** `ALLOW_ONLY_EXTERNAL_REGISTRATION=true`
  hides the self-registration form while still letting Authentik users onboard on first
  login. `DISABLE_REGISTRATION` stays `false` — flipping it true would block OIDC
  auto-create too.

## API Access

- **Base URL:** `https://git.dev.local/api/v1/`
- **Auth method:** token (`Authorization: token <token>`)
- **Bot account:** none. The playbook itself does **not** use a bot user — its own repo
  and Woodpecker wiring authenticate as the admin over **Basic auth on `127.0.0.1`**
  (`post-repo.yml`), precisely because a pre-provisioned token is wiped by a removal-reset.
- **Agent-forge token (opt-in):** with `gitea_agent_forge: true`, `post-forge.yml` mints a
  repo-scoped token named `nos-agent-forge` (scopes `["write:repository"]`) via
  `POST /api/v1/users/{admin}/tokens` and persists it in-role to
  **`~/.nos/secrets.yml` as `gitea_api_token`** — consumed by `tools/recipe-pr.sh`,
  `tools/nos-push`, and `tools/sync-trunk-to-gitea.sh`. Nothing writes
  `~/agents/tokens/gitea.token`.
- **Swagger:** `https://git.dev.local/swagger`

## Health Check

- **Endpoint:** `GET /api/v1/version` (container healthcheck: `curl -sf http://localhost:3000/api/v1/version`)
- **Expected:** `200 OK` with `{"version":"..."}`

## Metrics

- `/metrics` is enabled and **token-gated**: scrapers must send
  `Authorization: Bearer {global_password_prefix}_pw_gitea_metrics` (`gitea_metrics_token`).
  Alloy scrapes it through the published `127.0.0.1:3003` mapping.

## Dependencies

- None for storage — SQLite built in (`GITEA__database__DB_TYPE: sqlite3`)
- Authentik (native-OIDC SSO — optional; adds an `auth.<tld>` → host-gateway `extra_host`
  and, on local tenants, the mkcert root-CA mount so server-side OIDC discovery resolves)
- Woodpecker CI (CI/CD — optional; authenticates via a Gitea OAuth2 app)
- Mailpit (SMTP relay, only when `install_mailpit` — optional)
