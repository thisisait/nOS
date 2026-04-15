# INTEGRATION: pazny.nodered

Mechanical patches the parent agent applies after merging this role.

## 1. `default.config.yml` — install toggle
Insert immediately **after** the `install_n8n:` line (IIAB section, ~řádek 131):
```yaml
install_nodered: false            # Node-RED – low-code flow automation      [vyžaduje: Docker]
```

## 2. `default.config.yml` — `authentik_oidc_apps` entry
Append into the `# ── Proxy-auth služby (nginx forward auth, žádný nativní OIDC) ──` block (after the WordPress proxy entry, before the helper vars):
```yaml
  - name: "Node-RED"
    slug: "nodered"
    enabled: "{{ install_nodered | default(false) }}"
    launch_url: "https://{{ nodered_domain | default('nodered.dev.local') }}"
    external_host: "https://{{ nodered_domain | default('nodered.dev.local') }}"
    type: "proxy"
```

## 3. `default.config.yml` — helper vars
**Not applicable** — proxy-auth service, no `client_id` / `client_secret` helper vars needed.

## 4. `default.config.yml` — `authentik_app_tiers` entry
Add to `authentik_app_tiers:` (~řádek 1425, place alongside tier-2 entries — Node-RED function nodes grant shell-equivalent power, so manager tier):
```yaml
  nodered: 2
```

## 5. `default.credentials.yml` — new secrets
**Not applicable** — Node-RED is filesystem-only (no DB) and auth is delegated to Authentik. No credentials to provision.

## 6. `tasks/stacks/stack-up.yml` — role include
Insert into the `# IIAB roles` block (immediately after the `pazny.n8n render` line, ~řádek 70):
```yaml
- { name: "[Stacks] pazny.nodered render", ansible.builtin.include_role: { name: pazny.nodered, apply: { tags: ['nodered'] } }, when: "install_nodered | default(false)", tags: ['nodered'] }
```

## 7. `tasks/stacks/stack-up.yml` — `_remaining_stacks` update
**Not applicable** — `iiab` is always-active.

## 8. `tasks/stacks/stack-up.yml` — post.yml include
**Not applicable** — role has no `tasks/post.yml` (filesystem-only, no admin bootstrap).

## 9. Database provisioning
**Not applicable** — Node-RED persists flows, credentials, and installed nodes to the filesystem (`/data`).

## 10. Nginx vhost
Path: `templates/nginx/sites-available/nodered.conf`. Activates automatically via the `install_nodered` flag — `tasks/main.yml` symlinks it into `sites-enabled/` when the role runs.

## 11. `tasks/reset/` — external data path
**Not applicable** unless `nodered_external_data_dir_override` is later introduced (currently the role uses only the default `$HOME/nodered/data`).

## 12. Smoke test
```bash
ansible-playbook main.yml -K -e install_nodered=true --tags nodered
docker ps | grep nodered                              # should show "Up (healthy)"
curl -kI https://nodered.dev.local/                   # → 302 to Authentik login (with install_authentik=true)
curl -kI http://127.0.0.1:1880/                       # → 200 (direct, bypasses Authentik)
```

After Authentik login, the Node-RED editor should load at `https://nodered.dev.local/` with WebSocket live-updates functional (editor comms + debug sidebar).
