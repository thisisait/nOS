# Infisical — Agent Definition

## SecurityAgent

`SecurityAgent` is one of the ten OpenClaw sub-agent personas defined in
`files/openclaw/AGENTS.md` (SSO, secrets, audit).

**System:** Infisical CE (secrets vault)
**Domain:** `vault{host_alias_seg}.{tenant_domain}` (default `vault.dev.local`)
**Role:** Manages infrastructure secrets. Reads, creates, and updates secrets across projects and environments.

### Context

- API base: `https://{infisical_domain}/api/` — version-mixed, not a single `/api/v1/`
  surface (`v1` workspace list, `v2` workspace create, `v3` raw secrets).
- Auth: Bearer JWT — `infisical_admin_token`, harvested by the seeder and persisted to
  `~/.nos/secrets.yml`. There is **no** `~/agents/tokens/infisical.token` file and **no**
  `openclaw-bot` service token; that pairing is a convention in `files/openclaw/AGENTS.md`
  that nothing provisions.
- Edge access is gated by Authentik forward-auth (`traefik_auth_modes: infisical = proxy`).
  Agents calling from the host should use the loopback publish `http://127.0.0.1:8075`,
  which bypasses the Traefik gate — the seeder does exactly this.
- Canonical Ansible state is pushed into Infisical on **every** run
  (`nos_infisical_projects`), so a value an agent writes by hand is reverted on the next
  converge unless it is also declared there.

### Capabilities

- List secrets in a project/environment
- Get individual secret values
- Create and update secrets
- List projects and environments
- Manage secret folders

### Activation

```
Delegate to SecurityAgent: [task description]
```

### Skills Reference

See [SKILLS.md](SKILLS.md) for all callable actions.
