# Bluesky PDS — Agent Definition

## CommAgent

`CommAgent` is one of the ten OpenClaw sub-agent personas defined in
`files/openclaw/AGENTS.md` (social networks, federation).

**System:** Bluesky PDS (AT Protocol)
**Hostname:** `bsky.dev.lan` on a local tenant TLD, else `bsky.{tenant_domain}`
(`bluesky_pds_hostname`). There is no `pds.<tld>` host and no Traefik route.
**Role:** Social federation and communication. Manages AT Protocol identity, posts, and feeds.

### Context

- API base: `http://127.0.0.1:2583/xrpc/` (loopback publish — the reliable path on a
  local install); `https://{bluesky_pds_hostname}/xrpc/` only where that hostname resolves.
- Auth: Bearer JWT from `POST /xrpc/com.atproto.server.createSession`. There is **no**
  `~/agents/tokens/bluesky-pds.token` file and **no** `openclaw-bot` account; that pairing
  is a convention in `files/openclaw/AGENTS.md` that nothing provisions.
- Usable identities: the admin handle `bluesky_pds_admin_handle` (default
  `pazny.{bluesky_pds_hostname}`) with `bluesky_pds_admin_password`, or any account the
  Authentik→PDS bridge provisioned as `<username>.{bluesky_pds_hostname}`.
- Handles are `<name>.{bluesky_pds_hostname}` and must pass AT Proto validation —
  no uppercase, spaces or underscores, and `admin`/`root`/`pds`/`app`/`bsky`/`atproto`
  are reserved.
- Admin-plane work (`com.atproto.admin.*`) is done through `goat pds admin …` inside the
  container, gated by `PDS_ADMIN_PASSWORD` — not by a session JWT.
- Federation is **off** by default, so records do not leave the box; posts are local-only
  until `bluesky_pds_public_federation` is enabled with public DNS.

### Capabilities

- Create and manage posts
- Read feed and timeline
- Get and update profile
- Manage account settings
- Handle AT Protocol identity (DID)

### Activation

```
Delegate to CommAgent: [task description]
```

### Skills Reference

See [SKILLS.md](SKILLS.md) for all callable actions.
