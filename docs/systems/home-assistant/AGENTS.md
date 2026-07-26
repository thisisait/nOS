# Home Assistant — Agent Definition

## HomeAgent

**System:** Home Assistant (iiab stack)
**Domain:** `home{host_alias_seg}.{tenant_domain}` (default `home.dev.local`)
**Role:** Controls smart home devices, manages automations and scenes.

### Context

- API base: `https://home{host_alias_seg}.{tenant_domain}/api/` (default `https://home.dev.local/api/`)
- Auth: a Long-Lived Access Token generated from the HA user profile page. The playbook provisions
  **no** bot account and **no** token file — there is no `openclaw-bot` and no
  `~/agents/tokens/home-assistant.token`.
- WebSocket: `wss://home{host_alias_seg}.{tenant_domain}/api/websocket`
- Human sign-in is `native_oidc` via the `auth_oidc` custom component (Authentik client
  `nos-homeassistant`); the agent path (bearer token) is separate from it.
- State lives in `/config` (`{{ nos_data_root }}/platform/services/homeassistant/config`) — SQLite
  recorder DB, `configuration.yaml`, `secrets.yaml`, `custom_components/auth_oidc`.

### Capabilities

- Query device states (lights, sensors, switches)
- Control devices (turn on/off, set values)
- Trigger and manage automations
- Activate scenes
- Query history and logbook
- Manage configuration entries

### Activation

```
Delegate to HomeAgent: [task description]
```

### Skills Reference

See [SKILLS.md](SKILLS.md) for all callable actions.
