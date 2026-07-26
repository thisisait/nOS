# Portainer

> Docker management UI — containers, stacks, images, volumes. Tier-1 (admin-only)
> service in the `infra` stack. It does **not** hold the Docker socket: it talks to a
> hardened `docker-socket-proxy` sidecar (REM-001).

## Quick Reference

| | |
|---|---|
| **URL** | `https://portainer{host_alias_seg}.{tenant_domain}` (default `https://portainer.dev.local`) |
| **Port** | `9002` (`portainer_port`; loopback publish `127.0.0.1:9002` → container `9000`) |
| **Stack** | `infra` |
| **Node id** | `nos.infra.portainer` |
| **Toggle** | `install_portainer: true` |
| **Image** | `portainer/portainer-ce:2.33.8` (`portainer_version`) |
| **Compose** | `~/stacks/infra/docker-compose.yml` (+ override `~/stacks/infra/overrides/portainer.yml`) |
| **Data** | `{{ nos_data_root }}/platform/services/portainer/data` → `/data` (default `~/nos/platform/services/portainer/data`) — a **host bind mount**, not a Docker named volume |
| **Memory limit** | `1g` (`portainer_mem_limit` → `docker_mem_limit_standard`) |
| **Networks** | `infra_net` + the shared stacks network (`shared_net`) |

`portainer_version`, `portainer_domain` and `portainer_port` are pinned in
`default.config.yml` — that file **outranks** the role defaults. `portainer_data_dir`
has **no fallback** in `roles/pazny.portainer/templates/compose.yml.j2` (it is referenced
bare), so `default.config.yml` is its sole definition; an external-storage override
relocates it to `{{ external_storage_root }}/portainer` (`tasks/stacks/external-paths.yml`).
`post_blank` in `files/anatomy/plugins/portainer-base/plugin.yml` removes that directory
on a removal run.

Portainer is started with `--host tcp://docker-socket-proxy:2375 --http-enabled`.
`--http-enabled` matters: 2.19+ disables the plain-HTTP listener and 303-redirects
`:9000` to HTTPS, which would make the post-start readiness probe loop forever and
silently skip admin-init + OAuth setup. TLS is terminated by Traefik.

## Authentication

- **Admin user:** `admin`
- **Admin password:** `portainer_admin_password` = `{global_password_prefix}_pw_portainer`
  (`default.credentials.yml`). `tasks/post.yml` reconverges it via `PUT /api/users/1/passwd`
  (which needs the *old* password in the body, so it alternates candidates).
  Opt-in drift self-heal: `portainer_admin_auto_reset` (default `false`).
- **SSO bucket:** `native_oidc` (Authentik OAuth2 client `nos-portainer`), RBAC tier **1**
  (admin only). Wired by `PUT /api/settings` in `roles/pazny.portainer/tasks/post.yml` —
  the API is the live path, not compose env.
  Scopes `openid email profile`; redirect URI `https://{portainer_domain}`.
- **Autologin ceiling:** `OAuthSettings.HideInternalAuth=true` hides the internal
  username/password form (`autologin.supports: yes`), but Portainer offers **no
  auto-redirect** — the user still clicks the OIDC button. Dormant behind
  `sso_autologin: false`. Break-glass: `/#!/internal-auth`.

## API Access

- **Base URL:** `https://{portainer_domain}/api/` (host-side callers use
  `http://127.0.0.1:9002/api/`, which is what the playbook uses)
- **Auth method:** Bearer JWT from `POST /api/auth` (`{"Username": "...", "Password": "..."}`)
- **Credentials:** the `admin` account above. There is **no** `openclaw-bot` account and
  **no** `~/agents/tokens/portainer.token` file — that pairing is a convention in
  `files/openclaw/AGENTS.md` that nothing provisions.
- **Unauthenticated probe:** `GET /api/settings/public` returns `AuthenticationMethod`
  (`3` = OAuth2) — the playbook reads it to keep the OIDC wiring idempotent.

## Health Check

- **Manifest:** `type: tcp` on `portainer_port` — the manifest row does *not* define an
  HTTP health URL.
- **Live HTTP probe (plugin + role):** `GET /api/system/status` → `200`
  (`files/anatomy/plugins/portainer-base/plugin.yml` `wait_health`, and every
  `wait_url` in `roles/pazny.portainer/tasks/post.yml`). During the admin-init
  window the role also tolerates `303` (= up, but `AdminInitTimeout` has closed).
  `/api/status` is the legacy 1.x/early-2.x alias; `/api/system/status` is the
  endpoint nOS actually polls.

## Dependencies

- **`docker-socket-proxy`** (declared `depends_on`) — the hardened Docker API gateway
  defined in `templates/stacks/infra/docker-compose.yml.j2` and shared with Traefik.
  Portainer never mounts `/var/run/docker.sock` directly. Two flags trim its surface
  further: `portainer_socket_proxy_can_exec` (Portainer's web shell — the highest-impact
  RCE surface) and `portainer_socket_proxy_can_distribution` (registry pulls from the UI);
  both default `true`, set both `false` in `config.yml` to fully close REM-001 at a
  usability cost.
- Authentik (native-OIDC SSO — optional)
