# FreePBX — Agent Definition

## FreePBXAgent

**System:** FreePBX + Asterisk (PBX, taxonomy anchor `nos.voip.freepbx`)
**Domain:** `pbx.<tenant_domain>` (local default `pbx.dev.local`)
**Role:** Telephony control surface — extensions, trunks, dial plans, CDRs.

### Context

- Web UI: `http://127.0.0.1:8088/` → redirects to `/admin` (self-managed PHP session).
- Voice: SIP `5060`, IAX2 `4569`, RTP `10000-10100` (loopback unless LAN access enabled).
- Database: MariaDB `asterisk` (dialplan + hashed extension secrets).
- SSO: **none** — identity is the Asterisk extension number, not an Authentik subject.
- Data at rest: `{{ nos_data_root }}/platform/services/freepbx/data`.

### Capabilities

- **No agent-invocable API.** The upstream GraphQL/REST API is not enabled or
  credentialed by nOS (see [SKILLS.md](SKILLS.md)).
- Administration is human-driven in the web UI, or via `asterisk -rx` inside the
  container (`docker exec voip-freepbx-1 …`) — a host-shell action, not a service API.

### Caveats

- Vendor-blocked image (`tiredofit/freepbx`, abandoned 2022) with unfixable
  CRITICAL CVEs — supervised, opt-in only.

### Skills Reference

See [SKILLS.md](SKILLS.md) — this system has no external skill surface.
