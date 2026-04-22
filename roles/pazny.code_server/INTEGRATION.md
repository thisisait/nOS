# INTEGRATION: pazny.code_server

Mechanically applicable patch. The service runs inside the `devops` compose
stack. SSO = proxy auth (Authentik forward_auth). No DB, no post-start hook.

## 1. `default.config.yml` — install toggle

Insert after `install_paperclip: ...` line (~line 169):

```yaml
install_code_server: false       # code-server - VS Code in the browser [Docker, requires: Authentik for SSO]
```

## 2. `default.config.yml` — `authentik_oidc_apps` entry (proxy type)

Append to the `authentik_oidc_apps:` list in the "Proxy-auth services" block
(before the `authentik_oidc_*` helper vars, ~line 1608):

```yaml
  - name: "code-server"
    slug: "code-server"
    enabled: "{{ install_code_server | default(false) }}"
    launch_url: "https://{{ code_server_domain | default('code.dev.local') }}"
    external_host: "https://{{ code_server_domain | default('code.dev.local') }}"
    type: "proxy"
```

## 3. `default.config.yml` — helper vars

**Not applicable** — code-server uses proxy auth, no `client_id` /
`client_secret` is required.

## 4. `default.config.yml` — `authentik_app_tiers` entry

Add to `authentik_app_tiers:` (~line 1425):

```yaml
  code-server: 1
```

Tier 1 (admin) — code-server grants full shell access to the host; it must
not be reachable by non-admin users.

## 5. `default.credentials.yml` — new secrets

**Not applicable** — PASSWORD / HASHED_PASSWORD / SUDO_PASSWORD are
intentionally empty (authentication is handled by Authentik forward_auth). No
DB, no secrets.

## 6. `tasks/stacks/stack-up.yml` — role include

Insert into the "# DevOps roles" block (~line 82-86), after `pazny.paperclip render`:

```yaml
- { name: "[Stacks] pazny.code_server render", ansible.builtin.include_role: { name: pazny.code_server, apply: { tags: ['code-server'] } }, when: "install_code_server | default(false)", tags: ['code-server'] }
```

## 7. `tasks/stacks/stack-up.yml` — `_remaining_stacks` update

**Not applicable** — the `devops` stack is already in `_remaining_stacks` via
`gitea` / `paperclip` / `gitlab`.

## 8. `tasks/stacks/stack-up.yml` — post.yml include

**Not applicable** — the role has no `post.yml`.

## 9. Database provisioning

**Not applicable** — code-server is filesystem-only, no DB.

## 10. Nginx vhost

Path: `templates/nginx/sites-available/code-server.conf`.

The vhost activates automatically via `pazny.code_server/tasks/main.yml`
(symlinks `sites-available` -> `sites-enabled` when `install_code_server=true`
and `install_nginx=true`). Key points:
- `listen 443 ssl` + redirect from `:80`
- WebSocket upgrade mapping (`$http_upgrade` -> `$connection_upgrade`) — required
  for the integrated terminal + LSP
- `proxy_read_timeout 86400` — long-running terminal sessions
- `proxy_buffering off` — realtime output
- `include authentik-proxy-auth.conf` at location level
- `include authentik-proxy-locations.conf` at server level (outpost paths)

## 11. Smoke test

```bash
ansible-playbook main.yml -K -e install_code_server=true --tags code-server

docker ps | grep code-server                      # Up, healthy
curl -k -I https://code.dev.local                 # 200 or 302 to auth.dev.local
```

SSO verification:
1. Open `https://code.dev.local` in the browser
2. Authentik forward_auth redirects to `https://auth.dev.local/...`
3. After login (admin tier) the code-server UI opens without its own login prompt
4. Open the integrated terminal — WebSocket connect must succeed (otherwise the vhost
   has timeout / upgrade header issues)

Data persistence verification:
- `ls ~/code-server/config` — user settings, extensions
- `ls ~/code-server/workspace` — DEFAULT_WORKSPACE (project mount point)
