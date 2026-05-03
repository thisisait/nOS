# grafana-base — service plugin (DRAFT) + live wiring map

> **Status:** A6.5 PoC research artifact, captured 2026-05-03. The plugin
> manifest itself is **NOT loaded by any code** until the loader's
> side-effects land — but ALL the wiring it describes is **already LIVE
> via the pre-Q monolith pathways** (same shape as `qdrant-base`).
> This document is the canonical map between draft manifest blocks and
> their current live homes.

## What this plugin describes (post-Q target)

Connects `roles/pazny.grafana/` to anatomy as a **single removable
artifact**. Everything that's "wiring" rather than "install" lives here:

- Authentik OIDC client provisioning (today: row in `authentik_oidc_apps`)
- Datasources provisioning (Prometheus + Loki + Tempo + sqlite + postgres)
- 17 in-repo dashboards + optional grafana.com community dashboards
- Compose-extension fragment carrying all `GF_AUTH_*` env vars
- Wing /hub deep-link card (post-PoC)
- GDPR Article 30 row
- Plugin-self-metrics (provision success/fail counters)

## What's LIVE today (pre-Q monolith)

Each block in `plugin.yml` corresponds to a real live file or stanza:

| Plugin block | Live home today | Status |
|---|---|---|
| `authentik:` | `default.config.yml` `authentik_oidc_apps` row `slug: grafana` | ✅ live |
| `compose_extension:` (`GF_AUTH_GENERIC_OAUTH_*`) | `roles/pazny.grafana/templates/compose.yml.j2` env block | ✅ live |
| `provisioning.datasources` | `files/observability/grafana/provisioning/datasources/all.yml.j2` (rendered to `~/observability/grafana/provisioning/datasources/all.yml` by `tasks/observability.yml`) | ✅ live |
| `provisioning.dashboards_provider` | `files/observability/grafana/provisioning/dashboards/all.yml.j2` | ✅ live |
| `provisioning.dashboards.files` | `files/observability/grafana/provisioning/dashboards/*.json` (18 files incl. new `24-qdrant.json`) | ✅ live |
| `lifecycle.post_compose.wait_health` | `roles/pazny.grafana/tasks/post.yml` "Wait for Grafana HTTP API" task | ✅ live |
| `lifecycle.post_compose.admin_password_reconverge` | `roles/pazny.grafana/tasks/post.yml` "Reconverge admin password" task | ✅ live |
| `gdpr:` | (gap today — Wing /gdpr has no `grafana` row) | ⏳ closes post-Q |
| `ui-extension.hub_card` | (gap today — auto-derived from manifest in Q phase) | ⏳ closes post-Q |
| `notification.on_provision_failure` | (gap today — no failure routing) | ⏳ closes post-Q |
| `observability.metrics` (plugin self-metrics) | (gap today — no plugin-loader emission) | ⏳ closes A6.5 |

## What just landed alongside this map (commit `feat(grafana): conditional mkcert CA mount`)

Mirroring the **Open WebUI bug from 2026-05-03 morning**: Grafana
unconditionally mounted the mkcert root CA at `/etc/grafana/mkcert-ca.crt`
and pointed `GF_AUTH_GENERIC_OAUTH_TLS_CLIENT_CA` at it. That works on a
local TLD (`.dev.local`) where mkcert is the only CA in play, but on a
**public TLD with Let's Encrypt certs** the mkcert-only bundle shadows
Grafana's bundled Mozilla CA list — Authentik's LE cert can no longer be
validated, OIDC handshake fails. Same regression class Open WebUI already
fixed; Grafana now matches:

```jinja
{% if install_authentik | default(false) and (tenant_domain_is_local | default(true) | bool) %}
  - {{ stacks_dir }}/shared-certs/rootCA.pem:/etc/grafana/mkcert-ca.crt:ro
{% endif %}
...
{% if tenant_domain_is_local | default(true) | bool %}
  GF_AUTH_GENERIC_OAUTH_TLS_CLIENT_CA: "/etc/grafana/mkcert-ca.crt"
{% endif %}
```

## Why this exists

See `docs/bones-and-wings-refactor.md` §1.1 — "tendons & vessels" doctrine.
Today, ~70% of `roles/pazny.grafana/` is wiring rather than install. This
plugin extracts that 70% into a separate, modular, removable artifact
owned by the integration, not by the role.

The doctrine proof gate (A6.5) is: **fresh blank with thinned `pazny.grafana`
+ `grafana-base` plugin produces byte-identical functional Grafana**
(dashboards, datasources, OIDC, scrape, alerts all green; `diff` between
old `~/.nos/state.yml` snapshot and new shows only path drift).

That gate hasn't been crossed yet — this map captures the CURRENT live
shape so the future thin-role refactor has a side-by-side comparison
target.

## Edge cases

See `files/anatomy/docs/grafana-wiring-inventory.md` for the full catalog.
Headlines:

- **EC1:** Compose-template OIDC env block — resolved via plugin-emitted
  secondary override fragment (the "vessel" pattern).
- **EC2:** Admin-password reconverge — stays in role (install-internal state).
- **EC3:** `frser-sqlite-datasource` plugin install — defers to a future
  `wing-grafana` composition plugin (Q1).
- **EC5:** Plugin loader needs 4 lifecycle hooks (pre-render, pre-compose,
  post-compose, post-blank) — A6 foundation landed; side effects pending A6.5.

## Files (planned, A6.5 implementation phase)

When the loader's side effects are real, this directory grows:

| Path | Purpose |
|---|---|
| `plugin.yml` | Manifest (already drafted) |
| `templates/grafana-base.compose.yml.j2` | Vessel: OIDC env block (today: lives in role compose) |
| `provisioning/datasources/all.yml.j2` | MOVED from `files/observability/grafana/...` |
| `provisioning/dashboards/all.yml.j2` | MOVED |
| `provisioning/dashboards/*.json` | MOVED — 18 files |
| `notifications/provision-failed.txt` | Mail template |
| `notifications/provision-failed.ntfy` | Ntfy template |
| `tests/test_compose_extension_renders.py` | Schema + render parity test |
