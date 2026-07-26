# Portainer — Agent Definition

## MonitorAgent

> **Corrected:** this file previously named a `PortainerAgent`. No such persona exists.
> The OpenClaw roster in `files/openclaw/AGENTS.md` has exactly ten sub-agents, and
> containers/uptime belong to **`MonitorAgent`**.

`MonitorAgent` is one of the ten OpenClaw sub-agent personas defined in
`files/openclaw/AGENTS.md` (uptime, containers).

**System:** Portainer CE (infra stack)
**Domain:** `portainer{host_alias_seg}.{tenant_domain}` (default `portainer.dev.local`)
**Role:** Manages Docker containers, stacks, images, and volumes.

### Context

- API base: `https://{portainer_domain}/api/` — or `http://127.0.0.1:9002/api/` from the
  host (loopback publish; this is the path the playbook itself uses).
- Auth: Bearer JWT obtained from `POST /api/auth` with the `admin` account
  (`portainer_admin_password` = `{global_password_prefix}_pw_portainer`). There is **no**
  `~/agents/tokens/portainer.token` file and **no** `openclaw-bot` user; that pairing is a
  convention in `files/openclaw/AGENTS.md` that nothing provisions.
- Endpoint ID: `1` (the local Docker environment).
- Portainer reaches Docker through the `docker-socket-proxy` sidecar, so any capability
  the proxy does not expose is unavailable regardless of Portainer permissions — notably
  `exec` and registry `distribution` when
  `portainer_socket_proxy_can_exec` / `portainer_socket_proxy_can_distribution` are `false`.
- Stacks shown in the UI are Ansible-rendered compose projects. Editing one through
  Portainer is reverted on the next playbook run — treat the UI as read-mostly.

### Capabilities

- List and manage running containers
- Restart/stop/start services
- View container logs
- Manage Docker stacks
- Pull and manage images
- Monitor resource usage

### Activation

```
Delegate to MonitorAgent: [task description]
```

### Skills Reference

See [SKILLS.md](SKILLS.md) for all callable actions.
