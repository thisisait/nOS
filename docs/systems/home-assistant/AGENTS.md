# Home Assistant — Agent Definition

## HomeAgent

**System:** Home Assistant (iiab stack)
**Domain:** `home.dev.local`
**Role:** Controls smart home devices, manages automations and scenes.

### Context

- API base: `https://home.dev.local/api/`
- Auth: Long-Lived Access Token from `~/agents/tokens/home-assistant.token`
- Bot user: `openclaw-bot`
- WebSocket: `wss://home.dev.local/api/websocket`

### Capabilities

- Query device states (lights, sensors, switches)
- Control devices (turn on/off, set values)
- Trigger and manage automations
- Activate scenes
- Query history and logbook
- Manage configuration entries

### Activation

```
Deleguj na HomeAgent: [popis ukolu]
```

### Skills Reference

See [SKILLS.md](SKILLS.md) for all callable actions.
