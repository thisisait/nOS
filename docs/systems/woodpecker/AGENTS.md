# Woodpecker CI — Agent Definition

## WoodpeckerAgent

**System:** Woodpecker CI server + agent (`devops` stack, node `nos.devops.woodpecker`)
**Domain:** `ci.<tenant_domain>`
**Role:** Manages CI repo activation and reads pipeline state. Woodpecker runs the `.woodpecker.yml` pipeline on every Gitea push once a repo is activated.

### Context

- API base (loopback): `http://127.0.0.1:8060/api/`
- Auth: `Authorization: Bearer <woodpecker_api_token>` — an OAuth-derived PAT that does **not** exist until the operator has logged in once via Gitea OAuth2. On a fresh blank, API actions are skipped gracefully.
- Forge: Gitea (peer service). Repos are discovered via OAuth2 but each is dormant until explicitly activated.
- Agent runs pipeline steps in Docker via the mounted `/var/run/docker.sock`.

### Capabilities

- Refresh the forge cache (re-query Gitea for available repos).
- Check whether a repo is activated.
- Activate a repo by its Gitea `forge_remote_id`.
- Read the authenticated user.

### Constraints

- Blank-safe: with no valid token, every write is skipped, not fatal.
- No native OIDC / trusted-proxy mode — the agent cannot bypass the Gitea OAuth login chain.
- `/metrics` is bearer-gated with a separate `woodpecker_prom_token`, not the user PAT.

### Skills Reference

See [SKILLS.md](SKILLS.md) for callable actions.
