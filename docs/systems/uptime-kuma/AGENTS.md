# Uptime Kuma — Agent Definition

## MonitorAgent

**System:** Uptime Kuma (status monitoring)
**Domain:** `uptime.dev.local`
**Role:** Uptime and incident management. Monitors service availability and manages status pages.

### Context

- API base: `https://uptime.dev.local`
- Auth: API key from `~/agents/tokens/uptime-kuma.token`
- Bot user: `openclaw-bot`
- WebSocket-based API (socket.io) for real-time, REST for read operations

### Capabilities

- List and manage monitors
- Add new HTTP/TCP/DNS monitors
- Get current status of all services
- List and manage incidents
- View uptime history and statistics

### Activation

```
Deleguj na MonitorAgent: [popis ukolu]
```

### Skills Reference

See [SKILLS.md](SKILLS.md) for all callable actions.
