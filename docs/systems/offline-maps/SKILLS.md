# Offline Maps — Skills

> Honest scope note: Offline Maps has **no external skill surface** that nOS wires for agents.

## No invocable nOS action

tileserver-gl is a static tile server sitting behind a Traefik forward-auth gate. Its tile, style and TileJSON HTTP routes belong to tileserver-gl upstream and are consumed by browser map viewers, not by agents — nOS adds no management or provisioning API on top. There is nothing here to invoke, so no skill nodes are declared. Inventing an endpoint would be worse than this honest gap.

## Authentication

- **Method:** N/A — access is decided at the Traefik edge (Authentik `forward_auth`); the tile server itself issues no credential.

## Changing what is served

Adding or replacing map archives is a **playbook operation**, not an API call: set `maps_mbtiles_files` (or drop `.mbtiles` files into the data dir) and re-run the playbook. The role downloads/refreshes the archives and re-renders the tileserver config.

## Upstream reference

For the tile / style / TileJSON HTTP routes themselves, see tileserver-gl upstream: https://github.com/maptiler/tileserver-gl — these are not nОS-specific and are not asserted here to avoid shipping an endpoint that could drift.
