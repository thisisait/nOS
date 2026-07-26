# Backrest — Skills

> Honest scope note: Backrest has **no external skill surface** that nOS wires for agents.

## No invocable nOS action

Backup, restore, prune and DR-verify all happen inside backrest's web UI, which is loopback-bound and Authentik forward-auth gated (Tier 1). nOS does not wire an agent-facing REST API on top of it, and backrest's own auth is disabled precisely because access is decided at the edge. So no skill nodes are declared here — an invented backup/restore endpoint would be worse than this honest gap.

## Authentication

- **Method:** N/A — backrest's own login is disabled (`config.json` `auth.disabled: true`); the only gate is Authentik forward-auth at the Traefik edge (Tier 1 admin).

## Host daemon lifecycle (operator, not agent API)

These are host `launchctl` commands against the launchd label, not calls into backrest. They are the only programmatic control nOS exposes.

Check daemon state:

```bash
launchctl print "gui/$(id -u)/eu.thisisait.nos.backrest"
```

Restart the daemon (picks up a changed plist / binary):

```bash
launchctl kickstart -k "gui/$(id -u)/eu.thisisait.nos.backrest"
```

## Configuration is daemon-owned

`~/backrest/config/config.json` is seeded once by the playbook (`force: false`) and thereafter **rewritten by the daemon** (it adds sync identity, ids, modno, bcrypt hashes). Repos and plans are edited in the UI; hand-edits outside the seed window are not the supported path.
