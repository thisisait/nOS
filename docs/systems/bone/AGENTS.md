# Bone — Agent Definition

## BoneAgent

**System:** Bone (host organ, `nos.host.bone`)
**Bind:** `http://localhost:8099` (loopback only — no domain, no SSO)
**Role:** The state and dispatch bridge. Reads/writes nOS runtime state, triggers tagged playbook runs, drives migration/upgrade/coexistence recipes, and is the sink for telemetry events and notifications.

### Context

- API base: `http://localhost:8099/api/`
- Liveness (ungated): `GET /api/health`
- Privileged routes need a Bearer JWT from Authentik `client_credentials` whose `scope` covers the route (`nos:state:read`, `nos:run-tag`, …).
- The `/api/v1/events` sink authenticates by HMAC (`bone_secret`), not JWT.
- Source: `files/anatomy/bone/`; runtime state: `~/.nos`; Wing store: `~/wing/app/data`.

### Capabilities

- Read and write nOS runtime state (`/api/state`, `/api/state/services`).
- Trigger a tagged playbook run (`POST /api/run-tag`, scope `nos:run-tag`).
- Drive migrations, upgrades, patches, and coexistence recipes (plan / apply / rollback).
- Ingest telemetry events (`/api/v1/events`) and notifications (`/api/v1/notifications`).
- Report liveness and aggregate cluster health.

### Cautions

- `run-tag` executes `ansible-playbook main.yml --tags <tag>` on the host — it is a real mutation, gated by scope and a strict tag allow-list (`^[A-Za-z][A-Za-z0-9_,-]{0,99}$`).
- Migration/upgrade `apply` routes are not dry-runs; prefer `plan`/`preview` first.

### Skills Reference

See [SKILLS.md](SKILLS.md) for callable actions.
