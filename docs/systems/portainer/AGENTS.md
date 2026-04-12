# Portainer — Agent Definition

## PortainerAgent

**System:** Portainer (infra stack)
**Domain:** `portainer.dev.local`
**Role:** Manages Docker containers, stacks, images, and volumes.

### Context

- API base: `https://portainer.dev.local/api/`
- Auth: Bearer JWT from `~/agents/tokens/portainer.token`
- Bot user: `openclaw-bot`
- Endpoint ID: typically `1` (local Docker)

### Capabilities

- List and manage running containers
- Restart/stop/start services
- View container logs
- Manage Docker stacks
- Pull and manage images
- Monitor resource usage

### Activation

```
Deleguj na PortainerAgent: [popis ukolu]
```

### Skills Reference

See [SKILLS.md](SKILLS.md) for all callable actions.
