# ERPNext

> CRM/ERP system. Spravuje obchodni data, faktury, zakazniky a zasoby.

## Quick Reference

| | |
|---|---|
| **URL** | `https://erp{host_alias_seg}.{tenant_domain}` (default `https://erp.dev.local`) |
| **Port** | `8087` (`erpnext_port`; loopback publish `127.0.0.1:8087` → container `8080`) |
| **Stack** | `b2b` |
| **Toggle** | `install_erpnext: true` **plus** `erpnext_experimental_override: true` — the role hard-fails at load without the override (PARKED 2026-05-08) |
| **Compose** | `~/stacks/b2b/docker-compose.yml` (role fragment: `~/stacks/b2b/overrides/erpnext.yml`) |
| **Image** | `frappe/erpnext:v15.111.0` (`erpnext_version`) |
| **Data** | Docker **named volume** `erpnext_sites` (project-qualified `b2b_erpnext_sites`) — **no host bind mount** |
| **Mem / CPU** | `erpnext_mem_limit` (default `1g`) / `erpnext_cpus` (default `1.0`), per container |

**`erpnext_port` is `8087`, not the role default `8082`** — `default.config.yml` defines
the var and `vars_files` outrank role defaults, so the role's `8082` never wins. (8082 is
the Traefik dashboard.)

**ERPNext has no host data directory.** Since P0.1 (commit `3b88162`) the Frappe sites
tree lives in the Docker named volume `erpnext_sites` — macOS Docker Desktop VirtioFS
bind mounts are unstable for Frappe's filelock operations, so the volume keeps the data
inside the Docker VM on native ext4. `erpnext_data_dir` still exists in
`default.config.yml` but is **deprecated and unread** — no role task and no compose
volume references it. `state/manifest.yml` correspondingly carries no `data_path_var`
for erpnext. A blank reset clears it via `docker compose down -v` + `docker volume
prune -f -a`; to relocate it to external storage you move the whole Docker Desktop disk
image (Settings → Resources), not a path in `tasks/stacks/external-paths.yml`.

Six containers, not one: `erpnext-configurator` (one-shot site create), `-backend`,
`-frontend` (the published port), `-queue-short`, `-queue-long`, `-scheduler`.

## Authentication

- **Admin user:** `Administrator`
- **Admin password:** `{global_password_prefix}_pw_erpnext` (`erpnext_admin_password`; set
  by the configurator's `bench new-site --admin-password`, reconverged by `post.yml`)
- **SSO:** `native_oidc` (Authentik OAuth2 client `nos-erpnext`, slug `erpnext`), RBAC tier **2**.
  - Redirect URI: `https://{erpnext_domain}/api/method/frappe.integrations.oauth2_logins.custom?provider=Authentik`
  - Scopes: `openid`, `email`, `profile`
  - Wired as a Frappe `Social Login Key` doctype by `roles/pazny.erpnext/tasks/post.yml`.

## API Access

- **Base URL:** `https://erp.dev.local/api/resource/`
- **Auth method:** API key + secret (`Authorization: token <api-key>:<api-secret>`)
- **Bot account:** none provisioned. No playbook task creates an ERPNext API user, and
  nothing writes `~/agents/tokens/erpnext.token` — mint an API secret by hand in the UI
  (User → API Access) if an agent needs one.

## Health Check

- **Endpoint:** `GET /api/method/frappe.ping` (`state/manifest.yml` `health_check`, and
  the plugin's `lifecycle.post_compose.wait_health`)
- **Expected:** `200 OK` with `{"message": "pong"}`

## Dependencies

- MariaDB (site database — required; the configurator connects as `root`)
- Redis (cache / queue / socketio, DBs 0-2 — required)
- Authentik (native-OIDC SSO — optional)
- Mailpit (SMTP relay, only when `install_mailpit` — optional)
