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

## What's now LIVE (commit `dotáhnutí — 2026-05-03 evening`)

The wiring layer was promoted from "spec only" to "real, deployed via the
pre-Q monolith pathways" so the operator can verify SSO + observability
+ Bone/Wing glue end-to-end on the next blank:

- **Bone client** — `files/anatomy/bone/clients/qdrant_client.py` (real
  Python module, httpx-based, lazy singleton). Three endpoints exposed
  in `files/anatomy/bone/main.py`:
  `GET /api/v1/embeddings/health`, `POST /api/v1/embeddings/upsert`,
  `POST /api/v1/embeddings/search`. JWT-scoped (`nos:embeddings:read` /
  `:write`). Returns 503 when `QDRANT_URL` is empty.
- **Wing PHP client** — `files/anatomy/wing/app/Model/QdrantClient.php`
  (real PHP class, cURL-based, read-only by design — writes route through
  Bone for actor attribution). DI-registered in
  `files/anatomy/wing/app/config/common.neon`.
- **Bone plist env** — `roles/pazny.bone/templates/bone.plist.j2` now sets
  `QDRANT_URL` + `QDRANT_API_KEY` (empty when `install_qdrant=false`).
- **Wing compose env** — `roles/pazny.wing/templates/compose.yml.j2` now
  sets `QDRANT_URL` + `QDRANT_API_KEY_RO` + `BONE_URL` (was missing) +
  `BONE_SECRET` + `host.docker.internal:host-gateway` extra_hosts.
- **Prometheus scrape** — `files/observability/alloy/config.alloy.j2`
  has a `prometheus.scrape "qdrant"` block gated on `alloy_scrape_qdrant`
  (defaults to `install_qdrant`).
- **Grafana dashboard** — `files/observability/grafana/provisioning/
  dashboards/24-qdrant.json` (8 panels: collections gauge, pending ops,
  RSS, goroutines, REST/gRPC latency timeseries, Loki log pane).
- **Authentik proxy gate** — auto-derived from `apps/qdrant.yml`
  `nginx.auth: proxy` via `apps_runner` post-hook. RBAC tier 1 (admin
  only — raw vector DB UI is power-user territory).
- **Wing /hub card** — auto-emitted via `apps_runner` systems sync
  (Tier-2 manifest's meta + ports → SystemRepository row).
- **GDPR row** — auto-upserted via `apps_runner` `upsert-gdpr.php` from
  `apps/qdrant.yml` `gdpr:` block.

## ⚠️ Two-blank gotcha (first-deploy only)

**Bone + Wing read `QDRANT_API_KEY*` from env at process start.** On the
FIRST blank with `install_qdrant: true`:

1. `pazny.bone` renders the plist + starts Bone — but `app_secrets.qdrant`
   doesn't exist yet, so plist `QDRANT_API_KEY` is empty.
2. `apps_runner` later deploys Qdrant + generates the keys + persists to
   `credentials.yml` under `app_secrets.qdrant.PASSWORD_API` / `_RO_API`.
3. Bone is still running with empty key → `/api/v1/embeddings/upsert`
   returns 503 (`QDRANT_URL is empty`).

**Resolution:** run `ansible-playbook main.yml -K` a second time
(without `blank=true`) — pazny.bone re-renders plist with the freshly
persisted keys, launchctl picks up the new env, Wing FPM container
restarts likewise. Operator verification of "SSO works + Wing /hub card
appears + Qdrant container healthy" succeeds on the FIRST blank; "Bone
embeddings endpoints return real responses" requires the second run.

Future fix (post-A6.5): apps_runner notifies a bone+wing-restart handler
when `app_secrets.qdrant` changes during a single blank — closes the
gotcha to a one-blank flow.

## What this draft (the plugin manifest itself) STILL does NOT deliver

- **No loader integration.** Same gate as `grafana-base` and
  `woodpecker-base` drafts — A6.5 must finish loader side effects
  (`render_compose_extension`, `bootstrap_collections`,
  `register_bone_client`, `register_wing_client`,
  `register_prometheus_scrape`, `import_grafana_dashboard`) before this
  manifest is loaded directly. Until then the wiring is realized via
  the pre-Q pathways listed above; the manifest is the post-Q target.
- **No automatic collection bootstrap on first deploy.** The three
  reserved collections (`agent_outputs`, `system_metadata`,
  `cybersec_intel`) are declared in this manifest but won't be PUT into
  Qdrant until A6.5 makes the `bootstrap_collections` hook real OR an
  operator/conductor calls `POST /api/v1/embeddings/upsert` on each.
  Workaround until then: `curl -X PUT ... /collections/agent_outputs ...`
  manually with the auto-generated key from `credentials.yml`.

## What `apps/qdrant.yml` DOES deliver today

- `docker compose -p apps up qdrant` brings the container up.
- Authentik forward-auth gates `qdrant.apps.<tld>` to admin tier only.
- API keys generated via `$SERVICE_PASSWORD_API` /
  `$SERVICE_PASSWORD_RO_API` magic tokens (32-char random, persisted via
  apps_runner secret resolution).
- Healthcheck on `/healthz`; start_period 45s for memmap warm-up.
- GDPR Article 30 row populated — Wing /gdpr surfaces it on next sync.

## Operator verification recipe

To prove the wiring on the next blank:

1. **Enable Qdrant** in `config.yml` (gitignored operator overrides):

   ```yaml
   install_qdrant: true
   ```

2. **Run blank:**

   ```bash
   ansible-playbook main.yml -K -e blank=true
   ```

3. **First-blank checklist** (every line independent — green = wiring
   reached that surface):

   | Surface | Green when |
   |---|---|
   | Container | `docker compose -p apps ps qdrant` shows `(healthy)` |
   | API auth | `curl -k https://qdrant.apps.<tld>/dashboard` redirects to `auth.<tld>` (Authentik gate) |
   | Wing /hub card | `https://wing.<tld>/hub` shows a "Qdrant" tile linked to the dashboard |
   | GDPR row | `https://wing.<tld>/gdpr` shows a `qdrant` row with `legal_basis: legitimate_interests` |
   | Prometheus scrape | `curl -s http://localhost:12345/metrics \| grep qdrant_collections_total` returns a value |
   | Grafana dashboard | `https://grafana.<tld>/d/nos-qdrant` panel shows `noValue: no scrape` until first scrape lands (~30s), then live data |
   | API keys persisted | `grep -A2 qdrant credentials.yml` shows `PASSWORD_API` + `PASSWORD_RO_API` entries |

4. **Second run** (closes the 2-blank gotcha — propagates the keys into
   Bone/Wing env):

   ```bash
   ansible-playbook main.yml -K
   ```

   After this:

   | Surface | Green when |
   |---|---|
   | Bone embeddings probe | `curl -H "Authorization: Bearer <jwt>" http://127.0.0.1:8069/api/v1/embeddings/health` returns `{"status":"ok",...}` |
   | Wing PHP client | Wing presenters can call `$qdrant->listCollections()` (manual smoke from `wing-cli`) |

If any of the first-blank rows is RED, that's the wiring break to file
as `fix(qdrant):` against the relevant role/template.

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
