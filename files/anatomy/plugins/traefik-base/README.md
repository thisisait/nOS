# traefik-base

Tier-1 service plugin for Traefik, the nOS edge reverse proxy. Activates
whenever `install_traefik` is on (default `true`) and `roles/pazny.traefik`
is installed. Binds 80/443, serves Tier-1 services from a file provider
(YAML auto-derived from `state/manifest.yml`) and Tier-2 apps from a
Docker provider (labels on the `apps` compose stack). The plugin loader's
post-compose hook health-gates the dashboard `/ping` endpoint so
downstream Tier-1 plugins can assume the edge is live before they probe
their own upstreams.

No `authentik:` block here — Traefik IS the SSO front-proxy, not an OIDC
consumer. The `authentik@file` middleware (defined in the file provider's
`middlewares.yml`) is what Tier-1 routers + Tier-2 labels reference. For
the full SSO + middleware + TLS contract, see
[docs/traefik-primary-proxy.md](../../../../docs/traefik-primary-proxy.md).
