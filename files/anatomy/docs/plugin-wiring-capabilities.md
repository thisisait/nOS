# Plugin wiring capabilities — the uniform contract

> Status: 2026-05-23. Companion to `plugin-loader-spec.md` and
> `role-thinning-recipe.md`. Pinned by `tests/anatomy/test_plugin_wiring_contract.py`;
> measured by `tools/plugin-wiring-report.py`.

A service plugin (`files/anatomy/plugins/<svc>-base/plugin.yml`) wires its
service into the platform through a handful of optional manifest blocks. This
doc records **which blocks have a live consumer** (so backfilling them changes
runtime behaviour) versus **which are forward-ready metadata** (no consumer
yet — present so a future feature lights up automatically). The distinction
drove the 2026-05-23 wiring-unification pass: we backfilled the live-consumer
gaps and the high-signal metadata, and deliberately left the rest.

## Block → consumer map

| Block | Live consumer | Effect when present |
|-------|---------------|---------------------|
| `requires.feature_flag` | `load_plugins.run_hook` gating | Plugin hooks skip when the toggle is false. **Mandatory** for every `service` plugin (or `requires.app` for Tier-2). |
| `lifecycle.{pre_render,pre_compose,post_compose,post_blank}` | loader hook runner | Renders, dir setup, health waits, API replays, blank cleanup. |
| `compose_extension` | loader `render_compose_extension` | OIDC env / mkcert CA / extra_hosts injected into the stack override. Only services that *need* injection declare it — **not universal**. |
| `authentik` | `authentik-base` aggregator → blueprint | Registers an OIDC client / proxy provider. Only services with a login surface (native_oidc / forward_auth / header_oidc). |
| `notification` | `wing-base` aggregator → routing sidecar → Bone fallback | Severity→channel routing. **Canonical shape only** (see below). |
| `pulse` | `pulse-base` aggregator | Registers scheduled jobs. |
| `observability` | `_plugin_stack` reads `loki.labels.stack`; DAG edge on `scrape` | `metrics`/`dashboard` are **metadata** today (no aggregator). Stack label is optional — unresolved stack just means "never stack-filtered out". |
| `ui-extension.hub_card` | *(none yet)* | **Forward-ready metadata.** Wing /hub harvest is pending; cards are authored ahead of it. |

## Canonical notification shape (A9)

The `wing-base` aggregator reads **severity keys only**. Use:

```yaml
notification:
  on_critical: [wing-inbox, ntfy]
  on_high:     [wing-inbox, ntfy]
  on_medium:   [wing-inbox]
  on_low:      []
  on_info:     []
```

Channels: `wing-inbox | ntfy | mail`. The **emitter** decides which failure maps
to which severity (it POSTs `origin_plugin` + `severity`); the block only routes
a severity to channels. The legacy event-key shape (`on_<event>: {channels,
template}`) is **dead** — it referenced `notifications/*.txt` template files that
were never committed, and the aggregator never read its keys. All plugins were
normalized to the canonical shape on 2026-05-23.

## Uniform contract (enforced by CI)

`test_plugin_wiring_contract.py` pins:

1. Every `plugin.yml` validates against `state/schema/plugin.schema.json`.
2. Every `service` plugin declares a gate — `requires.feature_flag` **or**
   `requires.app`. (Closed qdrant-base's hole: it ran its `:6333` `wait_health`
   on every playbook run and degraded, because it had neither.)
3. A `feature_flag` resolves to a real toggle var in `default.config.yml`.
4. The plugin DAG resolves with no cycles.
5. `notification` blocks use a canonical severity key.

## 2026-05-23 backfill decisions

- **notification → 55/55.** Live consumer; uniform severity block appended to 50
  plugins, 5 legacy event-key blocks normalized.
- **ui-extension → 49/55.** Hub cards added to the 6 user-facing native_oidc web
  apps (gitlab, homeassistant, n8n, nextcloud, open-webui, outline). The
  remaining 6 (alloy, mariadb, postgresql, redis, watchtower, openclaw) are
  daemons/agents with no user-facing UI — correctly cardless.
- **authentik → unchanged (38/55).** The 17 "missing" are all correct-by-design:
  infra daemons with no login surface (mariadb, postgresql, redis, alloy, loki,
  tempo, prometheus, traefik, watchtower, smtp-stalwart), the IdP itself
  (authentik-base), AT-proto identity (bluesky-pds), no-SSO doctrine (freepbx,
  qgis-server), and API/S3 surfaces where forward-auth would break the API
  contract (mcp-gateway, rustfs, offline-maps). Blanket-filling would have
  broken the blank run.
- **observability → unchanged (38/55).** `metrics`/`dashboard` have no aggregator
  today; backfill is pure metadata. Deferred until the prometheus-base scrape
  harvest ships (post-Q1), at which point it becomes a real wiring backfill.

Re-measure anytime: `python3 tools/plugin-wiring-report.py [--gaps] [--strict]`.
