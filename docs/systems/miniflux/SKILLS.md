# Miniflux — Skills

> Miniflux has NO nOS-provisioned agent skill surface. This file says so plainly
> rather than transcribing endpoints the playbook does not wire — a confident wrong
> endpoint is worse than an honest absence.

## No wired agent surface

nOS deploys Miniflux as a human-facing RSS reader behind Authentik SSO. The playbook
provisions the SSO login and a bootstrap `admin` account, but it does NOT mint any
agent token or API key. There is nothing here for an agent to call with a
playbook-managed credential.

## The upstream REST API is opt-in and human-gated

Miniflux does ship a REST API upstream, but using it requires a user to create an
API key in the web UI (Settings → API Keys) first. That key is not generated,
stored, or referenced anywhere in the nOS repo, so its endpoints are deliberately
NOT documented here as verified facts. If an operator mints a key, the authoritative
reference is Miniflux's own upstream API docs — not this file.

## Access model

- Web UI: `https://{miniflux_domain}` behind Authentik `native_oidc` (tier 3).
- Loopback: `http://127.0.0.1:3011` (the debug publish; container binds `8080`).
- Store: the PostgreSQL `miniflux` database, not a file surface.
