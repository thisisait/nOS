# Offline Maps — Agent Definition

## OfflineMapsAgent

**System:** Offline Maps (tileserver-gl, iiab stack)
**Domain:** `maps.<tenant_domain>` (default `maps.dev.local`)
**Role:** Observes a static, forward-auth-gated tile server. It does not administer the service — there is no management API to drive.

### Context

- Serves vector + raster tiles from MBTiles archives under `{{ nos_data_root }}/tenants/{{ nos_tenant_slug }}/shared/maps/data`.
- No app-level authentication; access is decided at the Traefik edge (Authentik forward-auth).
- Tile / style / TileJSON HTTP routes are tileserver-gl's own upstream surface, consumed by browser map clients — nOS wires no agent-facing action on top of them.

### Capabilities

- Confirm liveness via `GET /` (forward-auth returns 401/302 when unauthenticated — still proof of life).
- Read which MBTiles archives are configured (`maps_mbtiles_files`, data dir contents).

### Non-capabilities

- No provisioning, no user management, no content upload API. Adding maps is a playbook operation (`maps_mbtiles_files` + a run), not an agent call.

### Skills Reference

See [SKILLS.md](SKILLS.md) — this service has no external skill surface.
