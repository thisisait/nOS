# Bone

> The local FastAPI organ — the bridge between Ansible runs and Wing's SQLite store. Signals: it carries state, migrations, upgrades, coexistence, events and notifications.

## Quick Reference

| | |
|---|---|
| **Toggle** | `install_bone: true` (`default.config.yml`) |
| **Kind** | Host launchd daemon — NOT a Docker service |
| **Bind** | `127.0.0.1:8099` (loopback only) |
| **Port** | `8099` (`bone_port`) |
| **Stack** | `host` (manifest `stack: null`) |
| **launchd label** | `eu.thisisait.nos.bone` |
| **App version** | `nOS Bone API` `0.2.0` (`FastAPI(title=..., version=...)`) |
| **Runtime dir** | `~/bone` (`bone_runtime_dir`) |
| **State dir** | `~/.nos` (`bone_state_dir`) |
| **Logs** | `~/bone/log` (`bone_log_dir`) |
| **Interpreter** | pyenv `python3` (macOS) / `/usr/bin/python3` (Linux) |

Bone runs the operator's own pyenv ansible directly (Anatomy A3a host-revert, 2026-05-03) — there is no bundled ansible-core. Source tree: `files/anatomy/bone/`.

## Routing

Bone has **no Traefik route**. Its id sits in `traefik_skip_ids` (`roles/pazny.traefik/vars/main.yml`) — "Bone is on host; published only on 127.0.0.1; reach via Wing UI". A `bone_domain` (`api.<tenant_domain>`) is defined in defaults but is not wired to the proxy today.

## Authentication

Two independent surfaces (`files/anatomy/bone/auth.py`):

- **Bearer JWT** — privileged routes (state writes, run-tag, migrations, upgrades, patches, coexistence) require a token from Authentik's OAuth2 `client_credentials` grant. The token's `scope` claim is checked against the route's required scopes (e.g. `nos:state:read`, `nos:run-tag`). Missing scope ⇒ `403`.
- **HMAC** — the `/api/v1/events` telemetry sink authenticates with a bare-hex HMAC over `"{timestamp}.{body}"` keyed on `bone_secret` (`hmac.compare_digest`, `sha256=` signature, timestamp-drift window). This lets Bone boot in HMAC-only mode (`BONE_REQUIRE_JWT_AUTH=0`) so the telemetry pipeline works without Authentik.

There is no per-user login and no SSO gate on the daemon itself — it is loopback and machine-facing.

## API / Health

- **Base URL:** `http://localhost:8099/api/`
- **Liveness:** `GET /api/health` — ungated, O(1). Returns `{"status":"ok","uptime":<s>,"auth_ready":<bool>}`. This is what launchd checks and `tools/nos-smoke.py` probes.
- **Aggregate health:** `GET /api/health/aggregate` — scope `nos:state:read`; fans out to every registered service (Wing `/timeline`, conductor readiness). NOT for smoke probes.
- **OpenAPI:** exportable via `files/anatomy/bone/bin/export-openapi.py`.

Route families under `/api/`: `state`, `migrations`, `upgrades`, `patches`, `coexistence`, `events`, `v1/notifications`, `v1/embeddings`, plus `run-tag`, `services`, `status`.

## Dependencies

- Ansible (the operator's pyenv `ansible-playbook` on `PATH`) — `run-tag` shells it.
- Wing SQLite store at `~/wing/app/data` (`bone_wing_db_dir`) — the events/notifications sink destination.
- `~/.nos/state.yml` — the runtime state side-car (`pazny.state_manager` generates it).
- Authentik (optional) — only when JWT auth is enabled; HMAC-only mode runs without it.
