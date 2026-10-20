# Gitea

> Self-hosted Git server. Repositories, issues, pull requests, webhooks.

## Quick Reference

| | |
|---|---|
| **URL** | `https://git{host_alias_seg}.{tenant_domain}` (default `https://git.dev.local`) |
| **Port** | `3003` (`gitea_port`; loopback publish `127.0.0.1:3003` → container `3000`) |
| **SSH** | `localhost:2222` (`gitea_ssh_port`; always loopback-bound → container `22`) |
| **Stack** | `devops` |
| **Toggle** | `install_gitea: true` (default `true`) |
| **Compose** | `~/stacks/devops/docker-compose.yml` (role fragment: `~/stacks/devops/overrides/gitea.yml`) |
| **Image** | `gitea/gitea:<gitea_version>` (pin in `default.config.yml`; 1.27.3 until the 28 recipe is proven) |
| **Data** | `{{ nos_data_root }}/platform/services/gitea/data` (default `~/nos/platform/services/gitea/data`) → `/data` |
| **Mem / CPU** | `gitea_mem_limit` (default `1g`) / `1.0` |

`nos_data_root` defaults to `~/nos` (`{{ HOME }}/nos`); `tasks/stacks/external-paths.yml`
relocates `gitea_data_dir` to `{{ external_storage_root }}/gitea` when external storage is
in play. The SQLite database, repositories, and LFS all live under that one `/data` mount.
Version history and the reason for every hop live in `upgrades/gitea.yml` (REM-099,
REM-137, REM-244, REM-294).

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

## Upgrading to Gitea 28 (REM-294)

Gitea dropped the `1.` prefix: **28.0.0 is the release after 1.27**, so 1.27.x → 28.1.0 is
one hop (recipe `gitea-1.27-to-28` in `upgrades/gitea.yml`). It is staged, not applied:
`gitea_version` stays 1.27.3 until the recipe has run on the estate.

What changes for nOS ([v28.0.0 notes](https://github.com/go-gitea/gitea/releases/tag/v28.0.0),
[go-gitea#39426](https://github.com/go-gitea/gitea/pull/39426)):

- **Egress.** `[security] ALLOWED_HOST_LIST` now covers webhooks **and OAuth2**, and the
  default `EGRESS_MODE=lax` denies every non-public host that is not listed. `auth.<tld>`
  resolves to host-gateway (private), so without it the Authentik login is denied. The
  template renders `ci.<tld>,auth.<tld>` there once `gitea_version >= 28`
  (`tests/anatomy/test_gitea_28_egress_names_auth.py`); the recipe adds the same key to the
  rendered override before the tag bump. `[webhook] ALLOWED_HOST_LIST` is deprecated.
  Lax mode lets webhooks reach public hosts; 1.27 allowed only the CI host.
- **Boot refusals.** A wildcard in `BLOCKED_DOMAINS`/`BLOCKED_HOST_LIST` stops 28 from
  starting; the recipe's `preflight_config` refuses before anything changes.
- **No way back by tag.** The schema moves forward and 1.27 refuses the migrated DB.
  Rollback stops the container, restores the data dir and the sqlite snapshot, then
  reverts the tag.
- **No effect here:** `[server] DOMAIN` is now derived from `ROOT_URL` (both come from
  `gitea_domain`); registration is set explicitly; Actions run retention (400 days) does
  not touch Woodpecker; the image ships Git 2.54 (28 needs ≥ 2.25).

To run it (operator):

```bash
ansible-playbook main.yml -K --tags upgrade -e upgrade_service=gitea \
  -e upgrade_recipe_id=gitea-1.27-to-28 -e upgrade_dry_run=true   # plan only
ansible-playbook main.yml -K --tags upgrade -e upgrade_service=gitea \
  -e upgrade_recipe_id=gitea-1.27-to-28                           # apply
```

Applied 2026-10-20: the estate runs 28.1.0 and the at-target entry is `gitea-28-current`. Before that, name the recipe id: in scan mode `gitea-1.27-current` sorted first and bounced the
container once for nothing. Optional rehearsal on cloned data: a coexistence track
(`coexistence_supported: true`, port 3013). Afterwards, the promoting MR moves
`gitea_version` to 28.1.0 and turns `gitea-1.27-current` into `gitea-28-current`, or the
next converge re-renders 1.27.3.
