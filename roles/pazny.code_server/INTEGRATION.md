# INTEGRATION: pazny.code_server

Mechanicky aplikovatelny patch. Sluzba bezi v `devops` compose stacku. SSO =
proxy auth (Authentik forward_auth). Bez DB, bez post-start hooku.

## 1. `default.config.yml` — install toggle

Insert after `install_paperclip: ...` line (~řádek 169):

```yaml
install_code_server: false       # code-server – VS Code v browseru [Docker, vyžaduje: Authentik pro SSO]
```

## 2. `default.config.yml` — `authentik_oidc_apps` entry (proxy type)

Append to `authentik_oidc_apps:` list v bloku "Proxy-auth služby" (pred
pomocnymi `authentik_oidc_*` helper vars, ~řádek 1608):

```yaml
  - name: "code-server"
    slug: "code-server"
    enabled: "{{ install_code_server | default(false) }}"
    launch_url: "https://{{ code_server_domain | default('code.dev.local') }}"
    external_host: "https://{{ code_server_domain | default('code.dev.local') }}"
    type: "proxy"
```

## 3. `default.config.yml` — helper vars

**Neaplikuje se** — code-server pouziva proxy auth, zadne `client_id` /
`client_secret` neni potreba.

## 4. `default.config.yml` — `authentik_app_tiers` entry

Add to `authentik_app_tiers:` (~řádek 1425):

```yaml
  code-server: 1
```

Tier 1 (admin) — code-server poskytuje plny shell pristup k hostu, nesmi byt
dostupny ne-admin uzivatelum.

## 5. `default.credentials.yml` — new secrets

**Neaplikuje se** — PASSWORD / HASHED_PASSWORD / SUDO_PASSWORD jsou zamerne
prazdne (autentikace resi Authentik forward_auth). Zadna DB, zadne secrets.

## 6. `tasks/stacks/stack-up.yml` — role include

Insert do bloku "# DevOps roles" (~řádek 82-86), za `pazny.paperclip render`:

```yaml
- { name: "[Stacks] pazny.code_server render", ansible.builtin.include_role: { name: pazny.code_server, apply: { tags: ['code-server'] } }, when: "install_code_server | default(false)", tags: ['code-server'] }
```

## 7. `tasks/stacks/stack-up.yml` — `_remaining_stacks` update

**Neaplikuje se** — `devops` stack uz je v `_remaining_stacks` kvuli `gitea`
/ `paperclip` / `gitlab`.

## 8. `tasks/stacks/stack-up.yml` — post.yml include

**Neaplikuje se** — role nema `post.yml`.

## 9. Database provisioning

**Neaplikuje se** — code-server je filesystem-only, zadna DB.

## 10. Nginx vhost

Cesta: `templates/nginx/sites-available/code-server.conf`.

Vhost se aktivuje automaticky pres `pazny.code_server/tasks/main.yml`
(symlink `sites-available` → `sites-enabled` kdyz `install_code_server=true`
a `install_nginx=true`). Klic:
- `listen 443 ssl` + redirect z `:80`
- WebSocket upgrade mapping (`$http_upgrade` → `$connection_upgrade`) — povinne
  pro integrovany terminal + LSP
- `proxy_read_timeout 86400` — long-running terminal session
- `proxy_buffering off` — realtime output
- `include authentik-proxy-auth.conf` na location level
- `include authentik-proxy-locations.conf` na server level (outpost paths)

## 11. Smoke test

```bash
ansible-playbook main.yml -K -e install_code_server=true --tags code-server

docker ps | grep code-server                      # Up, healthy
curl -k -I https://code.dev.local                 # 200 nebo 302 na auth.dev.local
```

Overeni SSO:
1. Otevri `https://code.dev.local` v browseru
2. Authentik forward_auth presmeruje na `https://auth.dev.local/...`
3. Po loginu (admin tier) se otevre code-server UI bez vlastni login vyzvy
4. Otevri integrovany terminal — WebSocket connect musi byt OK (jinak vhost
   timeout / upgrade headers)

Overeni data persistence:
- `ls ~/code-server/config` — User settings, extensions
- `ls ~/code-server/workspace` — DEFAULT_WORKSPACE (projekt mount point)
