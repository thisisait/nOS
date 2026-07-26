# Wing — Agent Definition

## WingAgent

**System:** Wing (host organ, `nos.host.wing`)
**Domain:** `wing.<tenant_domain>` (forward-auth gated) / `http://localhost:9000` on the loopback bind
**Role:** The observability + state dashboard. Reads the estate's systems inventory, remediation queue, audit events, migration/upgrade recipes, agent sessions and GDPR register from `wing.db`; exposes them as a browser UI and a Bearer-token JSON API.

### Context

- API base: `/api/v1/` (Nette `Api` module, `App\Presenters\Api\*`).
- API auth: `Authorization: Bearer <wing_api_token>` (validated via `TokenRepository`); per-agent tokens exist (`conductor_wing_api_token`, `openclaw_wing_api_token`, …).
- UI auth: Authentik forward-auth (tier 1 admin); the `X-Authentik-*` headers set the in-app Nette identity + RBAC tier.
- Store: `~/wing/app/data/wing.db` (SQLite) — written by Bone, read by Wing.
- Source: `files/anatomy/wing/`.

### Capabilities

- Query events, systems/components, remediation items, advisories, scan cycles, pentest findings.
- List and finish Pulse jobs/runs (`pulse_jobs`, `pulse_runs`).
- Inspect AgentKit agents and their sessions.
- Trigger a CI-style detached deploy (`POST /api/v1/deploy-trigger`).
- Read the GDPR Article-30 register, DSAR and breach records.

### Cautions

- `deploy-trigger` spawns a detached `ansible-playbook` run via `tools/deploy-from-ci.sh` on trusted branches only (`master` is operator-manual) — it is a real deploy, not a preview.
- Most `/api/v1/*` reads are safe; migration/upgrade `apply` routes mutate the estate.

### Skills Reference

See [SKILLS.md](SKILLS.md) for callable actions.
