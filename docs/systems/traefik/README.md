# Traefik

> Edge reverse proxy that binds 80/443 and front-fronts every Tier-1 (file provider) and Tier-2 (Docker provider) HTTP service in the fleet. It is the SSO front-proxy — it consumes the `authentik@file` forward-auth middleware; it is not itself an OIDC client.

## Quick Reference

| | |
|---|---|
| **Node** | `nos.infra.traefik` |
| **Edge** | `:80` → 301 `:443` (public on every interface) |
| **Dashboard/API** | `127.0.0.1:8082` (loopback only; `api.insecure: true`) |
| **Dashboard port** | `8082` (`traefik_dashboard_port`; container `:8080`) |
| **Domain** | `traefik.<tenant_domain>` (derived: `traefik{{ _host_alias_seg }}.{{ tenant_domain }}`; default tenant `dev.local`) |
| **Stack** | `infra` |
| **Toggle** | `install_traefik: true` |
| **Image** | `traefik:v3.6.23` (`traefik_image_version`) |
| **Compose** | `~/stacks/infra/docker-compose.yml` + `~/stacks/infra/overrides/traefik.yml` |
| **Container** | `infra-traefik-1` |
| **Config tree** | `~/stacks/infra/traefik` (`traefik_config_dir`) — `traefik.yml` + `conf.d/` (bind-mounted `:ro` at `/etc/traefik`) |

## Authentication

- **Admin user:** none. The dashboard runs `api.insecure: true` and is bound to `127.0.0.1:8082` — access control is the loopback bind, not a login.
- **SSO:** None on Traefik itself, by design. Traefik carries no `authentik:` plugin block: it IS the forward-auth front-proxy (`authentik@file` middleware in `conf.d/middlewares.yml`, fail-closed per PENTEST-002). Giving it its own OIDC client would gate the gate.

## Providers & routing

- **File provider** — `/etc/traefik/conf.d` (`traefik_dynamic_dir`, `watch: true`). Tier-1 routers/services are auto-derived from `state/manifest.yml` into `services.yml`; `middlewares.yml` + `tls.yml` alongside.
- **Docker provider** — `exposedByDefault: false`, endpoint `tcp://docker-socket-proxy:2375`, network `shared_net`. Tier-2 apps emit router labels on the apps stack.
- **TLS:** `websecure` uses `modern@file` options; encoded slash/backslash/null rejected at the entrypoint (path-traversal hardening).
- **Host loopback:** `extra_hosts` alias `nos-host:host-gateway` — file-provider routers reach Tier-1 upstreams published on `127.0.0.1:<port>`.

## API / Health

- **Base URL:** `http://127.0.0.1:8082` (read-only introspection API + dashboard; `api.dashboard: true`, `api.insecure: true`).
- **Health endpoint:** `GET /ping` → `200 OK` (manifest health check: `http://localhost:8082/ping`).
- **Config is NOT mutated via the API** — routing changes flow through the file/label providers only. There is no write surface. See [SKILLS.md](SKILLS.md).

## Networks

- `infra_net`, `shared_net`, `gated_net`, `gated_b2b_net` (`traefik_networks`) — must share a net with the SEC-02 header-trust backends it routes (calibre-web/2FAuth on `gated_net`; firefly on `gated_b2b_net`).

## Dependencies

- `docker-socket-proxy` (`depends_on`; the Docker provider endpoint).
- Authentik (supplies the `authentik@file` forward-auth outpost the middleware points at).

## Authoritative guide

`docs/traefik-primary-proxy.md` is the operator-facing source of truth for the SSO/middleware contract.
