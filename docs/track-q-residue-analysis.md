# Track Q Residue Analysis — 2026-05-05

> **Status:** Mid-Phase-1 stocktake. Captures which roles still carry
> `tasks/post.yml` cross-service wiring, why each one has not yet been
> migrated to a `files/anatomy/plugins/<name>-base/` manifest, and
> which roles are **legitimate exceptions** (post.yml is the right
> shape) vs. **pending Q1c/Q2 work**.
>
> Cross-references `docs/bones-and-wings-refactor.md` §1.1 (doctrine)
> + §13.1 (the 7-batch plan covering all `pazny.*` roles).

## Snapshot (post-Phase-1)

- **30** roles still carry `tasks/post.yml` (down from pre-Phase-1)
- **40** plugins live (Phase 1 batch shipped 33 new ones)
- **23** roles have BOTH a post.yml AND a corresponding plugin —
  Phase 2 C1+C5 will progressively shift cross-service wiring out of
  these post.yml files into plugin lifecycle hooks
- **7** roles have post.yml but NO matching plugin — analyzed below

## The 7 plugin-less post.yml roles

| Role | post.yml LOC | Category | Verdict |
|---|---|---|---|
| `pazny.apps_runner` | 485 | meta-orchestrator | **Exception** — keeps post.yml |
| `pazny.bluesky_pds` | 81 | identity | **Q3 candidate** |
| `pazny.bone` | 35 | anatomy host-binary | **Exception** — keeps post.yml |
| `pazny.mariadb` | 89 | database | **Exception** — keeps post.yml |
| `pazny.mcp_gateway` | 165 | API mesh | **Q3 candidate** |
| `pazny.postgresql` | 236 | database | **Exception** — keeps post.yml |
| `pazny.spacetimedb` | 132 | database (vector) | **Q3 candidate** |

## Per-role disposition

### `pazny.apps_runner` — Exception (485 LOC)

Meta-orchestrator for Tier-2 manifest-driven app onboarding (`apps/<name>.yml`).
Renders all per-manifest compose overrides into a single merged file,
brings up the apps stack, then fires 8 post-hooks (Bone events, smoke
catalog extension, Kuma monitor extension, Authentik blueprint
reconverge, GDPR upsert, Wing systems ingest, Portainer endpoint reg).

**Why no -base plugin:** apps_runner IS the plugin loader for Tier-2.
A "apps_runner-base" plugin would be a plugin loading other plugins —
recursive. The cross-service wiring here is the genuine deploy
choreography, not a wiring-leak. Keep in post.yml.

### `pazny.bone` — Exception (35 LOC)

Just installs venv + plist + restarts the launchd daemon. No
cross-service hooks. The 35-LOC post.yml is solely host launchd
plumbing.

**Why no -base plugin:** Bone is **part of the anatomy itself** (the
Bone bridge between Ansible runs and Wing's SQLite). It cannot
declare itself as a plugin to its own plugin loader. Same logic
applies to `pazny.wing` (covered as `wing-base` proxy-auth plugin
because Wing is also Authentik-gated for browser access — the plugin
declares the proxy gate, not Wing itself).

### `pazny.mariadb` — Exception (89 LOC)

Creates databases, runs `mysql_upgrade` on version transitions,
manages root password rotation. Pure DB admin, zero cross-service.

**Why no -base plugin:** Database substrate. Plugins consuming the
DB (vaultwarden-base, gitlab-base, n8n-base, etc.) declare their own
`requires.database: mariadb` in their plugin manifests; mariadb
itself is the substrate, not a wiring concern. Schema for plugin
declarations exists but loader's substrate-claim runner is C5 work.

### `pazny.postgresql` — Exception (236 LOC)

Larger than mariadb because Postgres carries `pgcrypto` extensions
+ per-service CREATE DATABASE + per-service CREATE USER + idempotent
ALTER ... SET — plus the 17→18 upgrade recipe wiring. Same exception
class as mariadb; substrate, not wiring.

### `pazny.bluesky_pds` — Q3 candidate (81 LOC)

post.yml runs the bridge that auto-provisions `@user.bsky.<tld>`
accounts from Authentik users. Cross-service surface: Authentik API
+ PDS API + state file at `~/.nos/bluesky-bridge/`.

**Q3 fit:** Yes — eligible for `bluesky-pds-base` plugin with
`lifecycle.post_compose: replay_api_calls` (same shape as U8's
nextcloud-base + gitea-base scaffolds). Loader runner needed: PDS
admin REST. Defer until Q3 batch (Storage+DB tier).

### `pazny.mcp_gateway` — Q3 candidate (165 LOC)

mcpo (Model Context Protocol gateway) — wires Open WebUI's MCP
client list, registers individual MCP servers (Grafana MCP, Wing
MCP if present), reconciles per-tool allowlists. Cross-service:
Open WebUI API + central MCP manifest.

**Q3 fit:** Yes — `mcp-gateway-base` plugin with
`lifecycle.post_compose: replay_api_calls`, peer plugins declaring
`mcp:` blocks aggregated by mcp-gateway-base (mirroring authentik-
base's aggregator pattern). Defer until Q3.

### `pazny.spacetimedb` — Q3 candidate (132 LOC)

Reactive client/server DB for real-time apps (similar role to qdrant
but for state sync). post.yml creates default modules + admin token.

**Q3 fit:** Yes — `spacetimedb-base` plugin with `requires.role`
+ minimal compose-extension. Defer until Q3 (substrate tier same
as qdrant).

## Phase 2 (C1+C5) implications

The 23 roles with BOTH post.yml AND plugin still have cross-service
wiring in post.yml that will progressively move into plugin lifecycle
hooks. This is **not** a Phase 1 task — Phase 1 only added the
plugins; Phase 2 C5 lands the loader's `replay_api_calls` runner
(docker_exec / occ-CLI / API-call sequences), and Phase 2 C1
deletes the central `authentik_oidc_apps` list (79 refs across the
codebase, pointing into many of those post.yml files).

After C5: each post.yml shrinks to install-only operations. The
operator's mental model becomes "role = install primitive, plugin
= wiring contract".

## Doctrine

> **A role's `tasks/post.yml` is legitimate** when it operates on
> **substrate** (databases, host services, anatomy bones) or **meta-
> orchestrates other deployables** (apps_runner). It is **wiring leak**
> when it operates on **another service's API/data plane** to satisfy
> SSO / observability / GDPR / hub-card requirements that should be
> the contract of a plugin manifest.

By that test, the 7 plugin-less roles' post.yml content is genuine
in 4 cases (apps_runner, bone, mariadb, postgresql) and is wiring
leak in 3 cases (bluesky_pds, mcp_gateway, spacetimedb) pending
the Q3 batch.

## Build sequence (Q1c → Q3 → Q4-Q7)

| Phase | Roles | Trigger | Status |
|---|---|---|---|
| **Q1c** | observability composition | Phase 1 | ✅ |
| **Q2** | 35 OIDC services | Phase 1 | ✅ |
| **D-series** | central `authentik_oidc_apps` retired; SSO trichotomy (`native_oidc / header_oidc / forward_auth`) | 2026-05-05 | ✅ — see `docs/native-sso-survey.md` + `docs/aggregator-parity-report.md` + `docs/upstream-pr-opportunities.md` |
| **D2** | drop role-side OIDC env duplicates (12 rolí) | active | 🟡 — outline prototype `2324b6d`; 11 zbývá |
| **Q3** | bluesky_pds, mcp_gateway (spacetimedb stub done) + 4 substrate exceptions | post-D2 | ⚪ |
| **Q4-Q7** | Comms / Content / Dev-CI / Misc tiers | operator bandwidth | ⚪ |

## D-series follow-ups (post-D2)

- Retire `authentik_oidc_<svc>_client_id/_secret` standalone helpers in
  `default.config.yml` once D2 finishes (no consumer left).
- Extend `run_aggregators` with `from: app_manifest` source so Tier-2
  apps land in `inputs.clients` alongside Tier-1 plugins (eliminates
  the empty `authentik_oidc_apps: []` Tier-2 stub).

This residue-analysis doc will be re-snapshotted after each Q-batch.
