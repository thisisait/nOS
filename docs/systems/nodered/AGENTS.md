# Node-RED — Agent Definition

## NodeRedFlows

**System:** Node-RED (iiab stack) — flow-based automation for IoT and integration.
**Domain:** `nodered{host_alias_seg}.{tenant_domain}` (default `nodered.dev.local`).
**Role:** A visual flow editor and runtime. Human-authored flows; not an agent target.

### Context

- Filesystem-only state in `/data` (`flows.json`, credentials, installed nodes) — no DB.
- Editor access is `native_oidc` (Authentik `passport-openidconnect`, β1.B), tier 2,
  with a break-glass local `admin` fallback in `adminAuth.users`.
- Health: `GET /` (a `401`/`302` from the SSO gate is healthy).

### Capabilities

- None wired for agents. nOS provisions no agent token for the Node-RED Admin API. The
  service's invocable surface is whatever HTTP-in flows the operator builds — those are
  user-defined, not a fixed API this doc can enumerate.

### For an agent

There is no nOS-provisioned agent surface. See `SKILLS.md`. Node-RED's Admin API exists
upstream but is gated by the `adminAuth` OIDC session with no provisioned agent
credential.
