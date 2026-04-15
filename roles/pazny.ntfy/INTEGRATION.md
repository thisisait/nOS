# INTEGRATION: pazny.ntfy

Service: ntfy (self-hosted push notifications, `ntfy.sh` upstream).
Stack: `iiab`. SSO strategy: **proxy** (Authentik forward-auth; ntfy has no native OIDC).
Tier: **2** (manager — publishing notifications is operator-level).

## 1. `default.config.yml` — install toggle

Insert **after** `install_uptime_kuma: false` (~line 138) in the IIAB section:

```yaml
install_ntfy: false               # ntfy – self-hosted push notifications server   [Docker]
```

## 2. `default.config.yml` — `authentik_oidc_apps` entry

Append to the **Proxy-auth** block of `authentik_oidc_apps:` (near line ~1523, after the `# ── Proxy-auth služby …` comment, grouped with the other `type: "proxy"` entries):

```yaml
  - name: "ntfy"
    slug: "ntfy"
    enabled: "{{ install_ntfy | default(false) }}"
    launch_url: "https://{{ ntfy_domain | default('ntfy.dev.local') }}"
    external_host: "https://{{ ntfy_domain | default('ntfy.dev.local') }}"
    type: "proxy"
```

## 3. `default.config.yml` — helper vars

**Not needed** — ntfy uses proxy auth only (no native OIDC client_id/client_secret).

## 4. `default.config.yml` — `authentik_app_tiers` entry

Add to `authentik_app_tiers:` (~line 1425, grouped with the other tier-2 managers next to `freescout: 2`):

```yaml
  ntfy: 2
```

## 5. `default.credentials.yml` — new secrets

**None.** ntfy stores its own ACL/tokens inside `cache.db` (SQLite). Nothing prefix-rotated.

## 6. `tasks/stacks/stack-up.yml` — role include

Insert into the **# IIAB roles** block (~line 67), alphabetically near `pazny.uptime_kuma`:

```yaml
- { name: "[Stacks] pazny.ntfy render", ansible.builtin.include_role: { name: pazny.ntfy, apply: { tags: ['ntfy'] } }, when: "install_ntfy | default(false)", tags: ['ntfy'] }
```

## 7. `tasks/stacks/stack-up.yml` — `_remaining_stacks` update

**Not needed** — `iiab` stack is already in the active loop.

## 8. `tasks/stacks/stack-up.yml` — `post.yml` include

**Not needed** — role has no `tasks/post.yml`. ntfy is self-initializing; admin users / ACL tokens can be seeded later via `docker exec ntfy ntfy user add …` (manual / follow-up role).

## 9. Database provisioning

**Not needed** — ntfy uses embedded SQLite (`cache.db` inside `{{ ntfy_data_dir }}`). No Postgres / MariaDB entry required.

## 10. Nginx vhost

- File: `templates/nginx/sites-available/ntfy.conf` (created by this role).
- Auto-activates when `install_ntfy: true` via the existing nginx vhost loop (`tasks/nginx/`), since the filename slug `ntfy` matches `install_ntfy`.
- Critical tuning for Server-Sent Events (SSE push): `proxy_buffering off`, `proxy_cache off`, `proxy_http_version 1.1`, `Connection ""`, `chunked_transfer_encoding off`, `proxy_read_timeout 300s`.
- Authentik forward-auth included via `authentik-proxy-locations.conf` + `authentik-proxy-auth.conf` snippets (same pattern as `uptime-kuma.conf`).

## 11. Smoke test

After `ansible-playbook main.yml -K -e install_ntfy=true --tags ntfy,nginx`:

```bash
# 1) Container up
docker ps --format '{{ "{{.Names}}\t{{.Status}}" }}' | grep ntfy

# 2) Local API reachable
curl -sS http://127.0.0.1:2586/v1/health
# → {"healthy":true}

# 3) Public vhost returns Authentik login (anonymous) then topic push after auth
curl -sk -o /dev/null -w '%{http_code}\n' https://ntfy.dev.local/
# → 302 to auth.dev.local/outpost.goauthentik.io/start (Authentik forward-auth)

# 4) Publish a test notification (after logging in / creating an access token)
curl -F "title=test" -d "hello from devBoxNOS" https://ntfy.dev.local/testtopic
# → JSON event with "id", "time", "event":"message"
```

Subscribe with the mobile app (ntfy.sh iOS/Android) or web UI:
pointing it at `https://ntfy.dev.local` + topic `testtopic`.
