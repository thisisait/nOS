# qdrant-base — service plugin (DRAFT)

> **Status:** research draft, 2026-05-03 evening. **NOT loaded by anything.**
> Second tune-and-thin pilot per `docs/active-work.md`. First pilot was
> Woodpecker (Tier-1 role); this one is the **first Tier-2-app + plugin
> pair**, proving the doctrine works for both deployment surfaces.

## What this delivers

Two paired artifacts:

1. **`apps/qdrant.yml`** (Tier-2 manifest) — installs Qdrant. Standalone
   usable today (`ansible-playbook main.yml -K --tags apps`).
2. **`files/anatomy/plugins/qdrant-base/plugin.yml`** (this draft) — wires
   Qdrant into the rest of the platform: Bone/Wing client glue, default
   collections, Grafana dashboard, Prometheus scrape, Loki labels.

## Use cases (forward-spec)

The plugin manifest reserves three first-class collections that future
agentic work fills:

| Collection | Purpose | Filled by |
|---|---|---|
| `agent_outputs` | Embeddings of agent run summaries (conductor / inspektor / gitleaks). One point per run. | A8 conductor + each plugin's skill runner |
| `system_metadata` | Wing `/systems` rows mirrored as embeddings — semantic search over the service catalog. | Pulse nightly job (post-A7) |
| `cybersec_intel` | CVE descriptions, advisories, remediation_items, vendor patches. | Conductor + ad-hoc ingest CLI |

These are scaffolding only — the plugin manifest declares the schema; the
actual ingestion lands with A8 (conductor agent) and A7 (gitleaks plugin's
finding-as-embedding flow).

## Tendons (anatomy autowiring)

- **GDPR delta** — apps/qdrant.yml has the canonical Article 30 row;
  this plugin adds `agent_prompt_context` + `advisory_text` data
  categories that the Bone redaction layer must strip before upsert.
- **Default-collection bootstrap** — `post_compose` hook calls Qdrant's
  REST API to PUT each of the three collections idempotently.
- **Wing /hub deep-link card** — admin-tier card pointing at the Qdrant
  dashboard.
- **Notifications** — collection-bootstrap-failure + health-loss routed
  to Wing inbox + ntfy.

## Vessels (infra wiring)

- **Bone integration** — adds `clients/qdrant_client.py` + `QDRANT_URL` /
  `QDRANT_API_KEY` env in Bone's launchd plist. Adds two routes:
  `POST /api/v1/embeddings/upsert` + `POST /api/v1/embeddings/search`.
  Gives agents a single API surface; the Qdrant key never leaves the host.
- **Wing integration** — adds `app/Model/QdrantClient.php` + read-only
  key env. Reserves `/vector-search` route for the future cross-collection
  similarity-search UI.
- **Prometheus scrape** — Alloy adds a `qdrant` job pointing at
  `qdrant:6333/metrics`. No auth required.
- **Loki labels** — `app=qdrant`, `stack=apps`, `tier=2` so log queries
  isolate Qdrant from other Tier-2 apps.
- **Grafana dashboard** — `dashboards/qdrant-overview.json` with
  collections gauge, query latency p99, pending operations queue depth,
  process_resident_memory (memmap warm-up watch).

## What this draft does NOT deliver yet

- **No loader integration.** Same gate as `grafana-base` and
  `woodpecker-base` drafts — A6.5 must finish loader side effects
  (`render_compose_extension`, `bootstrap_collections`,
  `register_bone_client`, `register_wing_client`,
  `register_prometheus_scrape`, `import_grafana_dashboard`) before any of
  these blocks have effect.
- **No Bone/Wing client code.** The PHP `QdrantClient.php` and Python
  `qdrant_client.py` files referenced in `bone_integration` /
  `wing_integration` are forward-specs. They're added when A6.5 lands +
  the conductor wants to call into Qdrant.
- **No dashboard JSON.** `dashboards/qdrant-overview.json` is a forward-
  spec path — actual JSON gets authored alongside the first scrape going
  live.

## What `apps/qdrant.yml` DOES deliver today

- `docker compose -p apps up qdrant` brings the container up.
- Authentik forward-auth gates `qdrant.apps.<tld>` to admin tier only.
- API keys generated via `$SERVICE_PASSWORD_API` /
  `$SERVICE_PASSWORD_RO_API` magic tokens (32-char random, persisted via
  apps_runner secret resolution).
- Healthcheck on `/healthz`; start_period 45s for memmap warm-up.
- GDPR Article 30 row populated — Wing /gdpr surfaces it on next sync.

## Reading order for the next agent

1. `apps/qdrant.yml` — the install half. Shows that a Tier-2 app can
   stand alone without any plugin.
2. This `plugin.yml` — the wiring half. Shows what gets added on top
   when A6.5 makes the loader real.
3. `files/anatomy/plugins/grafana-base/plugin.yml` — canonical reference
   for the block shape; service-type plugin bound to a `pazny.*` role.
4. `files/anatomy/plugins/woodpecker-base/plugin.yml` — sibling Tier-1
   pilot for comparison.

The Qdrant draft is the FIRST plugin manifest using `requires.app:` (Tier-2
binding) instead of `requires.role:` (Tier-1 binding). When A6.5 makes the
loader real, the Tier-2 binding mode is a small dispatch addition to
`load_plugins.py` — the rest of the lifecycle is identical.
