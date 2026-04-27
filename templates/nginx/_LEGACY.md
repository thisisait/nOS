# `templates/nginx/` — legacy archive

These vhost templates predate the Traefik edge proxy. They're kept as a
read-only archive for two narrow scenarios:

1. **Operator runs host nginx alongside Traefik** (`install_nginx: true` in
   `config.yml`). Even then, sites-enabled is empty by default — the
   operator opts in per-vhost via:
   ```yaml
   install_nginx: true
   nginx_sites_enabled:
     - gitea.conf       # only the vhosts they actually want
     - wing.conf
   ```
   `tasks/nginx.yml` deploys + symlinks only what's listed. Nothing
   auto-derives from `install_*` flags any more.

2. **Forensic / migration reference.** These configs document how each
   service was historically routed (auth_request snippets, fastcgi tuning,
   WebSocket upstreams, etc.). Useful when wiring a service into Traefik
   that needs an unusual middleware combination — copy the relevant
   `proxy_set_header` / `auth_request` patterns into a Traefik file-provider
   router instead of resurrecting the vhost.

## What runs by default

Traefik file provider (`roles/pazny.traefik/templates/dynamic/services.yml.j2`)
auto-derives one router + one service per `state/manifest.yml` entry whose
`install_flag` is on. Auth mode comes from
`roles/pazny.traefik/vars/main.yml` (`traefik_auth_modes`).

For Tier-2 apps (`apps/*.yml`) the runner emits Traefik labels via the
Docker provider. See `docs/playbook-event-hooks.md` and the upcoming
`docs/tier2-app-onboarding.md`.

## Don't add new vhosts here

If you need a new service routed: add it to `state/manifest.yml` (with
`domain_var` + `port_var`) and Traefik will pick it up automatically.
For per-app exotic routing, emit Docker labels directly in the role's
compose template.

This folder is **not** the place for new edge-routing logic.
