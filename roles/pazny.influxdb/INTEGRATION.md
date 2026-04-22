# INTEGRATION: pazny.influxdb

## 1. `default.config.yml` — install toggle

Insert after `install_observability: true` line (~row 122) in the **Observability** section:

```yaml
install_influxdb: false           # InfluxDB 2.x time-series DB  [requires: Docker, install_observability]
```

## 2. `default.config.yml` — authentik_oidc_apps entry (proxy type)

Append to the proxy-auth block in `authentik_oidc_apps:` (near Uptime Kuma / Calibre-Web entries):

```yaml
  - name: "InfluxDB"
    slug: "influxdb"
    enabled: "{{ install_influxdb | default(false) }}"
    launch_url: "https://{{ influxdb_domain | default('influx.dev.local') }}"
    external_host: "https://{{ influxdb_domain | default('influx.dev.local') }}"
    type: "proxy"
```

(No helper vars needed — InfluxDB uses proxy auth, not native OIDC.)

## 3. `default.config.yml` — authentik_app_tiers entry

Add to `authentik_app_tiers:` under Tier 1 (admin — metrics DB):

```yaml
  influxdb: 1
```

## 4. `default.credentials.yml` — new secrets

```yaml
influxdb_admin_password: "{{ global_password_prefix }}_pw_influxdb"
# influxdb_admin_token is auto-generated every run from main.yml (safe group)
# — see section 5 below. Keep a placeholder here only if you prefer a static token:
# influxdb_admin_token: "{{ global_password_prefix }}_pw_influxdb_token"
```

## 5. `main.yml` — auto-gen secret block entry

Append to the **safe group** `set_fact` block around line 372 (`Auto-regenerate stateless secrets`):

```yaml
        influxdb_admin_token: "{{ lookup('pipe', 'openssl rand -hex 32') }}"
```

Note: token is regenerated every run (safe group) because InfluxDB 2.x accepts
the token as env var at first-run only and subsequent runs re-auth via the
stored token in `/var/lib/influxdb2`. If you need stable token across runs
after first setup, move to `default.credentials.yml` and drop the `lookup()`.
**Recommended**: keep in safe group for now; document in README that token is
ephemeral until first `install_influxdb: true` run persists it in the volume.

Also gate the `when:` clause of the secret-regen block to include `install_influxdb`:

```yaml
      when: >
        (install_authentik | default(false)) or
        (install_infisical | default(false)) or
        (install_jsos | default(false)) or
        (install_erpnext | default(false)) or
        (install_outline | default(false)) or
        (install_superset | default(false)) or
        (install_influxdb | default(false))
```

## 6. `tasks/stacks/core-up.yml` — role include

**IMPORTANT**: InfluxDB belongs to the **observability** stack, which is
brought up in `core-up.yml` (not `stack-up.yml`). Insert after the
`pazny.tempo render` block (~row 218), still inside the
`# Observability roles` section:

```yaml
- name: "[Core] pazny.influxdb render"
  ansible.builtin.include_role: { name: pazny.influxdb, apply: { tags: ['influxdb', 'observability'] } }
  when:
    - install_observability | default(true)
    - install_influxdb | default(false)
  tags: ['influxdb', 'observability']
```

No post-start task is needed — InfluxDB auto-provisions admin user / org /
bucket / token on first container start via `DOCKER_INFLUXDB_INIT_*` env vars.

## 7. `tasks/stacks/stack-up.yml` — NO CHANGES

InfluxDB is in the observability stack (handled by `core-up.yml`). Do NOT
add anything to `stack-up.yml`.

## 8. Database provisioning

None — InfluxDB is itself a database (TSM engine, self-contained). No
external Postgres / MariaDB schema needed.

## 9. `tasks/reset/external-paths.yml` — blank reset path (optional)

If a user sets `influxdb_external_data_dir_override: /Volumes/SSD1TB/influxdb/data`,
the reset task must wipe that path too. Pattern follows existing services.

## 10. Nginx vhost (auto-activated)

File: `templates/nginx/sites-available/influxdb.conf` (created alongside this role).

Activated automatically by `tasks/nginx/` when `install_influxdb: true`
(matching `<service_slug>.conf` → `install_influxdb` flag pattern).

Forward-auth via Authentik is included on both `listen 443` vhost level and
inside `location /` (same pattern as Uptime Kuma). Cross-subdomain session
cookie (`.dev.local`) makes SSO transparent for users already logged into
Authentik.

## 11. Smoke test

After `ansible-playbook main.yml -K -e install_influxdb=true --tags influxdb`:

```bash
docker ps | grep influxdb                           # Up (healthy)
curl -sk https://influx.dev.local/health            # {"status":"pass", ...}
curl -sk https://influx.dev.local/                  # 302 → Authentik login (browser flow)
# API access with native token:
curl -sk -H "Authorization: Token $INFLUXDB_ADMIN_TOKEN" \
     https://influx.dev.local/api/v2/buckets        # JSON list incl. "default"
```

Browser test: navigate to `https://influx.dev.local/` → Authentik login →
InfluxDB UI. Log in with `admin` / `{{ influxdb_admin_password }}` (native
InfluxDB session, independent of Authentik identity).

## 12. Future work (NOT in this PR)

- **Grafana datasource auto-provisioning**: add InfluxDB entry to
  `files/observability/grafana/provisioning/datasources/all.yml.j2` using
  `{{ influxdb_admin_token }}` as the API token and `http://influxdb:8086`
  as the URL (container DNS on `observability_net`). Implement as a
  post-start task in `pazny.grafana` gated on `install_influxdb`.
- **Telegraf ingest sidecar**: optional role `pazny.telegraf` to ship
  host metrics into InfluxDB bucket.
