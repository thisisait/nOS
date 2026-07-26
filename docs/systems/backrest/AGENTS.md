# Backrest — Agent Definition

## BackrestAgent

**System:** Backrest (restic UI + scheduler, host launchd daemon)
**Domain:** `backrest.<tenant_domain>` (default `backrest.dev.local`), loopback `127.0.0.1:9898`
**Role:** Observes the off-site restic backup daemon. Backup, restore and DR-verify are driven through backrest's forward-auth-gated web UI by a Tier-1 operator — there is no nOS-wired agent API to invoke them.

### Context

- Runs as host launchd `eu.thisisait.nos.backrest`; its own login is disabled (`auth.disabled`), so Authentik forward-auth (Tier 1 admin) is the sole gate.
- Config `~/backrest/config/config.json` is owned and rewritten by the daemon — do not hand-edit expecting persistence; change repos/plans in the UI.
- Emits A9 notifications on backup/check/prune errors via `backrest-notify.sh` (Bone HMAC POST).

### Capabilities

- Confirm daemon liveness (`GET /` on loopback → 200).
- Read notification events routed through Bone/A9 (backup failures surface to `wing-inbox` + `ntfy` at `on_high`).

### Non-capabilities

- No agent-facing REST API for creating repos, running backups, or restoring — those are human, UI-mediated, admin-gated actions.
- Daemon lifecycle (start/stop/restart) is a host `launchctl` operation, not an application call.

### Skills Reference

See [SKILLS.md](SKILLS.md) — backrest has no external skill surface; only host daemon-lifecycle commands are documented there.
