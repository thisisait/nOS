# Backrest

> A restic backup UI + scheduler, run as a **host launchd daemon** (not a container). It orchestrates the off-site restic leg (copy #2) plus a restore UI and DR-verify. Complements `pazny.backup`'s app-consistent logical dumps (copy #1).

## Quick Reference

| | |
|---|---|
| **URL** | `https://backrest.<tenant_domain>` (derived from `backrest_domain`; default `backrest.dev.local`) |
| **Bind** | `127.0.0.1:9898` loopback only (`backrest_bind_addr:backrest_port`) |
| **Runtime** | host launchd daemon `eu.thisisait.nos.backrest` (not Docker) |
| **Binary** | `~/.local/bin/backrest` `v1.14.1` (`backrest_version`) |
| **Toggle** | `install_backrest: false` (default) |
| **Config** | `~/backrest/config/config.json` (seed-once; the daemon owns/rewrites it) |
| **Data** | `~/backrest/data` (`backrest_data_dir`); cache `~/backrest/cache` |
| **Manifest node** | `nos.host.backrest` |

> Why a host daemon, not a container: restic-in-container cannot read macOS VirtioFS bind mounts (0 files, "could not be read" — even though stat/cat/dd work). A native host binary reads the trees directly with operator permissions. Validated by the 2026-07-24 Phase-0 spike.

## Authentication

- **App-level auth:** disabled. `config.json` sets `auth.disabled: true` because backrest binds loopback only and the edge gate is the sole gate.
- **SSO bucket:** `forward_auth`, **Tier 1 (admin)**. The Traefik file provider derives `backrest.<tld>` → host-gateway `:9898` and applies the `authentik@file` middleware; a Tier-1 Authentik session (`nos-providers` / `nos-admins`) is required. backrest can read every backup and trigger restores, so it is admin-only.

## Health Check

- **Endpoint:** `GET /` on `http://localhost:9898/`.
- **Expected:** `200 OK` (manifest `health_check`, `type: http`).

## Role in the backup architecture

- **Backrest** = off-site (copy #2) restic orchestrator + restore UI + DR-verify. Seeded from the existing `restic_repo` when set; further edits are UI-managed.
- **`pazny.backup`** = on-host (copy #1) app-consistent logical dumps to RustFS.
- The two are complementary, not substitutes. See `docs/backup-architecture.md`.

## Dependencies

- restic (bundled in the backrest binary).
- A configured restic repository (`restic_repo` / `restic_password`) — e.g. an external SSD or remote object store.
- Bone (A9 notifications: `backrest-notify.sh` HMAC-POSTs hook events).
- Traefik + Authentik (edge forward-auth, Tier 1).
