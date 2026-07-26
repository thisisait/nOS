# Bluesky PDS

> AT Protocol Personal Data Server — identity and federation in a decentralised social
> network. Runs in the `infra` stack. It is the one nOS service with **no Traefik
> route**: AT Protocol forbids the `.local` TLD, so it lives on its own hostname and is
> reached over loopback or (with public DNS) over its federation hostname.

## Quick Reference

| | |
|---|---|
| **AT Proto hostname** | `bluesky_pds_hostname` — `bsky.dev.lan` on a local tenant TLD, else `bsky.{tenant_domain}`. **Not** `pds.<tld>`; that host does not exist anywhere in the tree |
| **Reachable at** | `http://127.0.0.1:2583` (loopback publish). **No Traefik router** — the `bluesky_pds` row in `state/manifest.yml` has no `domain_var`, so the file-provider loop skips it (`traefik_auth_modes: bluesky_pds = none`) |
| **Port** | `2583` (`bluesky_pds_port`; loopback publish `127.0.0.1:2583` → container `3000`) |
| **Stack** | `infra` |
| **Node id** | `nos.infra.bluesky-pds` (hyphen — the manifest id `bluesky_pds` is slugified; `_` is not a legal KEAP segment char) |
| **Toggle** | `install_bluesky_pds: true` |
| **Image** | `ghcr.io/bluesky-social/pds:0.4` (`bluesky_pds_version`; upstream ships no semver tags — `0.4` tracks current) |
| **Container** | `infra-bluesky-pds-1` (manifest id uses `_`, the compose service uses `-`) |
| **Compose** | `~/stacks/infra/docker-compose.yml` (+ override `~/stacks/infra/overrides/bluesky-pds.yml`) |
| **Data** | `{{ nos_data_root }}/platform/services/bluesky_pds/data` → `/pds` (default `~/nos/platform/services/bluesky_pds/data`) — `PDS_DATA_DIRECTORY=/pds`, blobstore at `/pds/blocks`, SQLite repo alongside |
| **Memory limit** | `512m` (`bluesky_pds_mem_limit` → `docker_mem_limit_light`) |
| **Networks** | `infra_net` + the shared stacks network (`shared_net`) |

Note the segment spelling: the data dir uses an **underscore** (`…/services/bluesky_pds/data`,
`default.config.yml`) while the compose override file and the external-storage override use a
**hyphen** (`overrides/bluesky-pds.yml`, `{{ external_storage_root }}/bluesky-pds`). Both are
current; they are simply not the same string.

An **opt-in** host-nginx vhost (`templates/nginx/sites-available/bluesky-pds.conf`, rendered only
when `install_nginx: true`) serves `bsky.dev.lan` + `*.bsky.dev.lan` over TLS and 301-redirects the
muscle-memory `bsky.{tenant_domain}` typo to the canonical `.lan` host.

## Authentication

- **Admin password:** `bluesky_pds_admin_password` = `{global_password_prefix}_pw_bluesky`
  (`default.credentials.yml`) — this is `PDS_ADMIN_PASSWORD`, used for the
  `com.atproto.admin.*` surface and the `goat pds admin` CLI.
- **Admin account:** `bluesky_pds_admin_handle`, default `pazny.{bluesky_pds_hostname}`
  (e.g. `pazny.bsky.dev.lan`). Created and password-reconverged by
  `roles/pazny.bluesky_pds/tasks/post.yml` via `goat pds admin account create` /
  `update-password` executed **inside** the container.
  AT Protocol reserves `admin`, `root`, `pds`, `app`, `bsky`, `atproto` — never use those as a handle.
- **Other secrets:** `bluesky_pds_jwt_secret` (`PDS_JWT_SECRET`) and
  `bluesky_pds_rotation_key` (`PDS_PLC_ROTATION_KEY_K256_PRIVATE_KEY_HEX`, auto-generated on a
  removal run).
- **SSO:** N/A — AT Protocol native auth (`traefik_auth_modes: bluesky_pds = none`); the plugin
  carries no `authentik:` block by design, because AT identities are DID-backed, not OIDC clients.
- **Identity bridge:** `tasks/stacks/bluesky_pds_bridge.yml` reads Authentik users and
  auto-provisions `<username>.{bluesky_pds_hostname}` accounts (skipping `akadmin` and any
  username that fails AT Proto handle validation). Invite ceremony is handled internally by
  `goat pds admin account create`; `bluesky_pds_invite_required` is now PDS-side config only.

## API Access

- **Base URL:** `http://127.0.0.1:2583/xrpc/` from the host; `https://{bluesky_pds_hostname}/xrpc/`
  only where that hostname actually resolves (opt-in nginx vhost, or public DNS + federation).
- **Auth method:** Bearer JWT from an AT Protocol session
  (`POST /xrpc/com.atproto.server.createSession`).
- **Credentials:** the admin handle + `bluesky_pds_admin_password` above, or a bridge-provisioned
  per-user account. There is **no** `openclaw-bot` account and **no**
  `~/agents/tokens/bluesky-pds.token` file — that pairing is a convention in
  `files/openclaw/AGENTS.md` that nothing provisions.
- **Admin-side operations** go through `goat pds admin …` inside the container
  (`docker compose -p infra exec -T bluesky-pds`), not through a host token.

## Health Check

- **Endpoint:** `GET /xrpc/_health` → `200 OK` with `{"version": "..."}`
  (manifest, the container healthcheck's `wget --spider`, the role's readiness probe and the
  plugin `wait_health` all agree on this one).

## Federation

Off by default (`bluesky_pds_public_federation: false`). Turning it on requires all four of:
a public tenant TLD (not `.local`/`.lan`/`.test`), a DNS A record for `bsky.<tenant_domain>`,
an ACME cert covering it, and inbound 443. The PDS works locally without federation — the flag
only controls whether external relays (`bsky.network`) accept records from it. AppView defaults
are `bluesky_pds_appview_url` = `https://api.bsky.app` / `bluesky_pds_appview_did` =
`did:web:api.bsky.app`.

## Dependencies

- None for storage — embedded SQLite under `/pds`, no shared PostgreSQL/MariaDB.
- Public DNS + TLS + inbound 443 for federation only (see above).
