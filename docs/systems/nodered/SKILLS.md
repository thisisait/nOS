# Node-RED — Skills

> Node-RED has NO nOS-provisioned agent skill surface. This file states that plainly
> rather than inventing endpoints — a confident wrong endpoint is worse than an honest
> absence.

## No wired agent surface

nOS deploys Node-RED as a human-facing flow editor behind Authentik native OIDC. The
playbook wires the editor's `adminAuth` OIDC strategy and a break-glass local admin,
but it provisions NO agent token and NO API credential. There is nothing here for an
agent to call with a playbook-managed credential.

## The Admin API is session-gated, not agent-wired

Node-RED ships an Admin HTTP API upstream, but under nOS it sits behind the
`adminAuth` OIDC session. No headless agent token is created, stored, or referenced
in the repo, so those endpoints are deliberately NOT documented here as verified
facts.

## The real invocable surface is operator-defined

What Node-RED exposes to callers is whatever HTTP-in nodes the operator wires into
their flows — arbitrary, per-install paths that cannot be enumerated from repo source.
Document those alongside the flows that create them, not here.

## Access model

- Editor: `https://{nodered_domain}` behind Authentik `native_oidc` (tier 2).
- Loopback: `http://127.0.0.1:1880` (debug publish; container binds `1880`).
- Store: filesystem `/data` (`flows.json`, credentials, installed nodes) — no DB.
