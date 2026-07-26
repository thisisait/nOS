# Vaultwarden

> Bitwarden-compatible personal password vault for tenants. Rust server, embedded SQLite,
> `iiab` stack. End-to-end encrypted: the master password derives the client-side
> decryption key, which is why SSO can gate the *login* but never the *unlock*.

## Quick Reference

| | |
|---|---|
| **URL** | `https://pass{host_alias_seg}.{tenant_domain}` (default `https://pass.dev.local`) |
| **Port** | `8062` (`vaultwarden_port`; loopback publish `127.0.0.1:8062` → container `80`, plain HTTP — TLS is terminated by Traefik) |
| **Stack** | `iiab` |
| **Node id** | `nos.iiab.vaultwarden` |
| **Toggle** | `install_vaultwarden: true` |
| **Image** | `vaultwarden/server:1.36.0` (`vaultwarden_version`) |
| **Compose** | `~/stacks/iiab/docker-compose.yml` (+ overrides `~/stacks/iiab/overrides/vaultwarden.yml` and `…/vaultwarden-base.yml`) |
| **Data** | `{{ nos_data_root }}/platform/services/vaultwarden/data` → `/data` (default `~/nos/platform/services/vaultwarden/data`) — SQLite `db.sqlite3`, RSA keys and encrypted attachments |
| **Memory limit** | `512m` (`vaultwarden_mem_limit` → `docker_mem_limit_light`) |
| **Networks** | `iiab_net` + the shared stacks network (`shared_net`) |

`vaultwarden_version`, `vaultwarden_domain` and `vaultwarden_port` are pinned in
`default.config.yml` — that file **outranks** the role defaults. `vaultwarden_data_dir` is
defined only in `default.config.yml`; an external-storage override relocates it to
`{{ external_storage_root }}/vaultwarden` (`tasks/stacks/external-paths.yml`).

**A removal run does NOT wipe this directory.** `files/anatomy/plugins/vaultwarden-base/plugin.yml`
uses a `conditional_remove_dir` gated on `vaultwarden_blank_destroys_vault` (default `false`):
the vault DB and attachments are encrypted under each user's master password, so losing them is
irreversible. Opt in deliberately.

`vaultwarden_signups_allowed` is `false` — accounts are created by the admin, not self-service.

## Authentication

- **Admin panel:** `https://{vaultwarden_domain}/admin`
- **Admin token:** `vaultwarden_admin_token` = `{global_password_prefix}_pw_vaultwarden_admin`
  (`default.credentials.yml`; note the `_admin` suffix). Printed by the role and stored in
  `~/.nos/secrets.yml`.
- **SSO bucket:** `native_oidc` (Authentik OAuth2 client `nos-vaultwarden`), RBAC tier **3** (user).
  Wired by the plugin compose-extension when `install_authentik` is on: `SSO_ENABLED=true`,
  `SSO_CLIENT_ID=nos-vaultwarden`, `SSO_AUTHORITY=https://{authentik_domain}/application/o/vaultwarden/`,
  `SSO_PKCE=true`. Redirect URI `https://{vaultwarden_domain}/identity/connect/oidc-signin`;
  scopes `openid email profile`.
- **`SSO_ONLY`:** `vaultwarden_sso_only`, default **`false`**. Setting it `true` removes the
  password login path so Authentik becomes the sole authenticator — the operator's account must
  already exist first, and break-glass is `/admin` or a re-render with the flag back off.
- **Permanent ceiling (not a bug):** after the SSO bounce the **master password is still required
  to unlock the vault** — it derives the client-side E2E key, which SSO cannot supply. No fork or
  env removes this, which is why `autologin.supports` is hard-locked `"no"`. This is
  click-the-button SSO, never true autologin.
- **mkcert trust:** on a local TLD the plugin mounts `~/stacks/shared-certs/rootCA.pem` and
  overrides the entrypoint to run `update-ca-certificates` before `/start.sh`, so the Rust TLS
  stack trusts Authentik. On a public TLD that mount is deliberately skipped — it would shadow
  the Mozilla bundle and break LE validation.

## API Access

- **Base URL:** `https://{vaultwarden_domain}/api/` (Bitwarden-compatible)
- **Auth method:** Bearer token from the Bitwarden identity flow
  (`POST /identity/connect/token`), obtained with a real user's credentials.
- **There is no agent identity here.** No `openclaw-bot` account and no
  `~/agents/tokens/vaultwarden.token` file are provisioned — that pairing is a convention in
  `files/openclaw/AGENTS.md` that nothing creates. More fundamentally, vault items are
  **end-to-end encrypted**: even an authenticated API caller receives ciphertext and cannot
  decrypt it without the user's master-password-derived key. Treat agent read access to vault
  contents as unavailable, not merely unconfigured.

## Health Check

- **Endpoint:** `GET /alive` → `200 OK`.
- **Flag (source, not doc):** the plugin's `post_compose` `wait_health` targets
  `https://127.0.0.1:{{ vaultwarden_port }}/alive`, but the container publishes plain **HTTP**
  on that loopback port (`127.0.0.1:8062:80`). The scheme in the plugin manifest does not match
  the published listener; the correct probe is `http://127.0.0.1:8062/alive`.

## Dependencies

- None for storage — embedded SQLite under `/data`, no shared PostgreSQL/MariaDB.
- Authentik (native-OIDC SSO — optional)
