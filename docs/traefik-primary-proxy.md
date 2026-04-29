# Traefik as primary edge proxy

As of C1 (2026-04-29), Traefik in a container is the **default and
only** edge proxy on a fresh nOS install. Host nginx (Homebrew) is
opt-in only via `install_nginx: true`, retained as a fallback for
operators with bespoke vhost-level constraints. The `pazny.nginx_container`
role and the legacy host-nginx-to-container migration (the D1 layer)
have been removed — they shipped briefly and never landed on a
deployed instance.

> **Why the cutover?** A reverse proxy that requires a Homebrew
> install pins nOS to macOS for the front door. Containerising it is
> a precondition for the Linux port. We considered nginx-in-container
> but Traefik's two-provider model (Docker labels for Tier-2,
> file provider for Tier-1) lets us auto-derive routing from
> `state/manifest.yml` without touching the existing 50+ `pazny.*`
> roles, which made the cutover materially cheaper.

---

## Architecture

Traefik runs as the `traefik` service in the `infra` compose stack.
It binds 80/443 unconditionally and reads two providers:

```yaml
# roles/pazny.traefik/templates/traefik.yml.j2 (static config)
providers:
  docker:
    exposedByDefault: false   # explicit opt-in via labels
    network: shared_net
  file:
    directory: /dynamic
    watch: true
```

### File provider (Tier-1)

`/dynamic/services.yml` is rendered from `state/manifest.yml` —
every service with `domain_var` + `port_var` set in the manifest
gets a router + service block. No per-role edits — one central YAML.

`/dynamic/middlewares.yml` defines:

- `authentik@file` — forward-auth → `http://authentik-server:9000/outpost.goauthentik.io/auth/traefik`
- `security-headers@file` — HSTS + content-type-nosniff + XSS filter
- `compress@file` — gzip + brotli
- `noverify@file` — `serversTransport` for self-signed upstream HTTPS

### Docker provider (Tier-2)

Apps in the `apps` compose stack emit Traefik labels in their compose
service block. The runner (`library/nos_apps_render.py`) auto-generates
labels from the manifest:

```
traefik.enable=true
traefik.docker.network=shared_net
traefik.http.routers.<slug>.rule=Host(`<slug>.apps.<tld>`)
traefik.http.routers.<slug>.entrypoints=websecure
traefik.http.routers.<slug>.tls=true
traefik.http.services.<slug>.loadbalancer.server.port=<port>
traefik.http.routers.<slug>.middlewares=authentik@file,security-headers@file,compress@file
```

The middleware list drops `authentik@file` for `nginx.auth: none` /
`oidc` apps.

### TLS

Traefik reads the same cert path nginx used to read
(`{{ tls_cert_path }}` / `{{ tls_key_path }}`). mkcert wildcards or
real LE wildcards Just Work — the `pazny.acme` task drops a copy at
`{{ traefik_certs_dir }}` so the file provider can mount it
read-only.

For a brand-new dev box, mkcert produces `*.dev.local` wildcards via
`pazny.dotfiles` and the rest is automatic.

---

## Tier-1 vs Tier-2

| Layer  | How services get routed                                               | Source of truth                |
| ------ | --------------------------------------------------------------------- | ------------------------------ |
| Tier-1 | File provider — `traefik_dynamic_dir/services.yml` rendered from manifest | `state/manifest.yml`           |
| Tier-2 | Docker provider — labels emitted by `nos_apps_render`                 | `apps/<name>.yml` manifests    |

**Why both?** The Tier-1 catalog is operator-edited per-instance via
the `install_*` flag set; routing it through file-provider keeps the
50+ existing `pazny.*` roles unmodified. The Tier-2 catalog is YAML-
driven by manifests — labels in compose are the natural fit for
templates the runner generates from a single source.

---

## Authentik forward-auth flow

User hits `https://<service>.<tld>` →

1. Traefik `authentik@file` middleware fires →
2. `http://authentik-server:9000/outpost.goauthentik.io/auth/traefik`
   over Docker DNS →
3. Authentik returns 302 → `https://auth.<tld>/...` →
4. User logs in (or session cookie matches) →
5. Authentik returns 302 → original URL →
6. Traefik forwards the request with `X-authentik-username`,
   `X-authentik-groups`, `X-authentik-email`, `X-authentik-name`,
   `X-authentik-uid` headers set →
7. Backend application sees the headers, treats user as logged in.

The `Location` rewrite (so the browser sees `auth.<tld>` instead of
the Docker-internal name) is handled by Authentik's outpost; we don't
patch headers at the Traefik level.

---

## Operator quick reference

### Where things live

```
roles/pazny.traefik/
  defaults/main.yml
  tasks/main.yml                  # renders all of the below
  templates/
    compose.yml.j2                # the traefik service definition
    traefik.yml.j2                # static config (entryPoints, providers)
    dynamic/middlewares.yml.j2    # authentik forward-auth + headers
    dynamic/services.yml.j2       # file provider — Tier-1 routes
```

### Inspecting routing at runtime

```bash
# All routers (Tier-1 + Tier-2 combined)
curl -s http://127.0.0.1:8080/api/http/routers | jq '.[].name'

# A specific router's full config (rule, service, middlewares, status)
curl -s http://127.0.0.1:8080/api/http/routers/<slug>@docker | jq

# Live config from the file provider
curl -s http://127.0.0.1:8080/api/http/services | jq '.[] | select(.provider=="file")'
```

The dashboard at `http://127.0.0.1:8080` (insecure-mode binding only
to loopback) shows the same data graphically.

### Forcing a reload of file-provider config

`watch: true` is set in static config — Traefik picks up edits to
`{{ traefik_dynamic_dir }}/*.yml` within seconds. No restart needed.
Edits to the COMPOSE labels of a Tier-2 app DO require a re-up of the
container.

### Falling back to host nginx

```yaml
# config.yml
install_traefik: false
install_nginx: true
```

Re-runs the playbook in the host-nginx-only path. Tier-2 apps_runner
is incompatible with host nginx (the Docker provider has nothing to
scrape) — they'll render the compose override but the Traefik labels
won't be picked up. Use Tier-2 only when Traefik is the active edge.

---

## Migration from host nginx (historical)

The host-nginx-only era ended in C1 (2026-04-29). The C1 commit
removes:

- `roles/pazny.nginx_container/` (the never-deployed bridge role)
- `docs/nginx-container-migration.md` (the D2 operator guide)
- `migrations/2026-05-15-nginx-host-to-container.yml` (the unfired migration)

Existing instances on host nginx need a single blank run to flip:

```bash
ansible-playbook main.yml -K -e blank=true
```

`tasks/nginx.yml` is gated behind `install_nginx | default(false)` —
the host nginx pieces stop being installed unless you explicitly opt
in. The playbook regenerates everything from scratch with Traefik as
the edge.

If you have bespoke vhost templates in `templates/nginx/sites-extra/`
or `nginx_sites_extra` and don't want to lose them, set
`install_nginx: true` AND `install_traefik: true` — they coexist on
different ports (Traefik on 80/443, nginx on whatever you bind it to)
but you'll be responsible for upstream wiring yourself. Most operators
don't need this.
