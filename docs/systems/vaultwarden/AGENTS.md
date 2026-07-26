# Vaultwarden — Agent Definition

## SecurityAgent

`SecurityAgent` is one of the ten OpenClaw sub-agent personas defined in
`files/openclaw/AGENTS.md` (SSO, secrets, audit).

**System:** Vaultwarden (personal password vault)
**Domain:** `pass{host_alias_seg}.{tenant_domain}` (default `pass.dev.local`)
**Role:** Password management — **operational only**. Agents cannot read vault contents.

### Context

- API base: `https://{vaultwarden_domain}/api/` (Bitwarden-compatible), or
  `http://127.0.0.1:8062/api/` from the host (loopback publish, plain HTTP).
- Auth: Bearer token from the Bitwarden identity flow (`POST /identity/connect/token`) with a
  real user's credentials. There is **no** `~/agents/tokens/vaultwarden.token` file and **no**
  `openclaw-bot` account; that pairing is a convention in `files/openclaw/AGENTS.md` that
  nothing provisions.
- **Hard ceiling:** vault items are end-to-end encrypted under each user's master-password-derived
  key. An authenticated API caller gets ciphertext. "Read-only agent access to vault items" is
  not a permission that can be granted — it is cryptographically unavailable.
- Admin-plane operations use the `/admin` panel with `vaultwarden_admin_token`
  (`{global_password_prefix}_pw_vaultwarden_admin`, stored in `~/.nos/secrets.yml`).
- Data is **preserved** across removal runs unless `vaultwarden_blank_destroys_vault: true`.

### Capabilities

- Check service liveness and version
- Read admin-panel diagnostics and user list (admin token)
- Confirm SSO wiring (`SSO_ENABLED`, `SSO_ONLY`) and signup policy
- **Not** available: reading, searching, creating, updating or deleting vault items —
  see the E2E ceiling above.

### Activation

```
Delegate to SecurityAgent: [task description]
```

### Skills Reference

See [SKILLS.md](SKILLS.md) for all callable actions.
