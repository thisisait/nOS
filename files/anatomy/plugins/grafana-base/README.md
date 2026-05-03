# grafana-base — service plugin (DRAFT)

> **Status:** A6.5 PoC research artifact, captured 2026-05-03. Not loaded by
> any code yet. The implementation phase will reify the manifest into actual
> wiring once the plugin loader (A6) lands.

## What this plugin does (when implemented)

Connects `roles/pazny.grafana/` to anatomy:

- Authentik OIDC client provisioning
- Datasources provisioning (Prometheus + Loki + Tempo + sqlite + postgres)
- 17 in-repo dashboards + optional grafana.com community dashboards
- Compose-extension fragment carrying all `GF_AUTH_*` env vars (the role's
  compose template sheds these — see EC1 in the wiring inventory)
- Wing /hub deep-link card (post-PoC)
- GDPR Article 30 row (closes a today's gap — Grafana has no GDPR row yet)
- Plugin-self-metrics (provision success/fail counters)

## Why this exists

See `docs/bones-and-wings-refactor.md` §1.1 — "tendons & vessels" doctrine.
Today, ~70% of `roles/pazny.grafana/` is wiring rather than install. This
plugin extracts that 70% into a separate, modular, removable artifact owned
by the integration, not by the role.

## Files (planned, A6.5 implementation phase)

| Path | Purpose |
|---|---|
| `plugin.yml` | Manifest (this directory's `plugin.yml` — already drafted) |
| `templates/grafana-base.compose.yml.j2` | Vessel: OIDC env block + plugin install env, merged into observability stack via Docker Compose `-f` discovery |
| `provisioning/datasources/all.yml.j2` | (MOVED from `files/observability/grafana/`) |
| `provisioning/dashboards/all.yml.j2` | (MOVED) |
| `provisioning/dashboards/*.json` | (MOVED — 17 files) |
| `notifications/provision-failed.txt` | Mail template |
| `notifications/provision-failed.ntfy` | Ntfy template |
| `tests/test_compose_extension_renders.py` | Schema + render parity test |

## Edge cases

See `files/anatomy/docs/grafana-wiring-inventory.md` for the full catalog.
Headlines:

- **EC1:** Compose-template OIDC env block — resolved via plugin-emitted
  secondary override fragment (the "vessel" pattern).
- **EC2:** Admin-password reconverge — stays in role (install-internal state).
- **EC3:** `frser-sqlite-datasource` plugin install — defers to a future
  `wing-grafana` composition plugin (Q1).
- **EC5:** Plugin loader needs 4 lifecycle hooks (pre-render, pre-compose,
  post-compose, post-blank) — A6 spec input.

## Forward-compat note

This manifest validates against the (planned) `state/schema/plugin.schema.json`
shape. When A6 lands, this directory becomes the canonical reference for
service-plugin authors. The `_template/` directory will be cloned from this
once it's operator-validated against a real blank.
