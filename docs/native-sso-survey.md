# Native SSO Survey — proxy-auth services

> **Updated 2026-05-20** — post-β1 status pass. Original audit shipped
> 2026-05-05 to plan the β1.A/B/C work; this revision marks what
> actually landed vs. what's still in the backlog.
>
> Audits which currently-proxy-auth services in nOS could be upgraded
> to **native OIDC** with Authentik — giving operators true SSO
> (auto-provisioned user accounts + role mapping inside the service)
> instead of just access control at the outpost.
>
> Source of truth for the current bucket of each service:
> per-plugin `authentik.mode:` in `files/anatomy/plugins/<svc>-base/plugin.yml`.
> The central `authentik_oidc_apps` list in `default.config.yml` was
> retired in D1.3 (2026-05-05) and survives only as an empty Tier-2
> apps_runner channel.

## Verdict matrix (post-β1 state)

| Service | Image | Today's mode | Native-OIDC verdict | Status |
|---|---|---|---|---|
| **firefly** | `fireflyiii/core:6.x` | `header_oidc` | `LOGIN_PROVIDER=remote_user_guard` injects identity via Authentik outpost headers. True SSO from user POV (auto-creates the account), just not via OAuth2 protocol. | ✅ **β1.A shipped 2026-05-05** — reclassified `header_oidc` |
| **nodered** | `nodered/node-red:4.x` | `native_oidc` | `passport-openidconnect` wired into `/data/settings.js::adminAuth.strategy`. Toggle: `nodered_native_oidc_enabled` (default true). | ✅ **β1.B shipped 2026-05-05** |
| **metabase** | `metabase/metabase:0.50+` | `forward_auth` | OAuth/SAML in Metabase OSS is paywall-gated (Pro tier). Community issue [#28195](https://github.com/metabase/metabase/issues/28195) tracks demand. | ❌ **β1.C deferred** — license-gated upstream |
| **uptime-kuma** | `louislam/uptime-kuma:1` | `forward_auth` | v1.x no OIDC. v2.x beta has env-driven OIDC. | ⏳ **Defer** — await v2 stable |
| **calibre-web** | `lscr.io/linuxserver/calibre-web` | `forward_auth` | OAuth2 limited to Github + Google fixed clients (no generic OIDC). | ⏳ **Upstream PR queued** — see `upstream-pr-opportunities.md` |
| **kiwix** | static reader | `forward_auth` | No auth model upstream. | ✅ **Stay proxy permanently** — no per-user state |
| **paperclip** | own fork | `forward_auth` | Plugin manifest explicitly declares "no native OIDC support". | ⏳ **Upstream PR queued** |
| **puter** | `nos/puter` | `forward_auth` | Plugin-based; would need a Puter OIDC plugin (TS). | ⏳ **Defer** — write a Puter plugin |
| **wing** | host launchd | `forward_auth` | Wing has built-in Nette\Security; today gated by proxy outpost. Native OIDC = Wing 2.0 work. | ⏳ **Defer** — Wing 2.0 |
| **code-server** | `lscr.io/linuxserver/code-server` | `forward_auth` | Coder OSS supports `--auth oauth-proxy` but LSIO image strips it. | ⏳ **Upstream PR queued** |
| **ntfy** | `binwiederhier/ntfy` | `forward_auth` | Only basic auth + tokens upstream; maintainer has OIDC on roadmap. | ⏳ **Upstream PR queued** |
| **onlyoffice** | `onlyoffice/documentserver:9.x` | `forward_auth` | DocServer is a render backend (B2B JWT). No end-user app. | ✅ **Stay proxy permanently** |
| **influxdb (OSS)** | `influxdb:2.7` | `forward_auth` | OIDC is Enterprise-gated. | ✅ **Stay proxy permanently** (until licensing pivot) |
| **mailpit** | `axllent/mailpit` | `forward_auth` | Dev SMTP capture; multi-user OIDC is out of scope upstream. | ✅ **Stay proxy permanently** |
| **spacetimedb** | DB binary protocol | `forward_auth` | No end-user web UI. | ✅ **Stay proxy permanently** |
| **openclaw** | host launchd | `forward_auth` | Local LLM gateway; admin-only surface. | ✅ Tier-1 admin proxy |
| **qdrant** | `qdrant/qdrant:v1.13.x` | `forward_auth` | Vector DB; no per-user state. | ✅ **Stay proxy permanently** |
| **snappymail** | `djmaze/snappymail-docker` | `forward_auth` | Webmail; IMAP account = identity inside the app. | ✅ Tier-3 proxy (correct mode) |
| **woodpecker** | `woodpeckerci/server:v3.x` | `forward_auth` (over Gitea-OAuth app-auth) | App-level auth is Gitea OAuth; Authentik gates the route. Stacked but intentional. | ✅ Working as designed |

## β1 retrospective (shipped 2026-05-05)

### β1.A — `firefly` → `header_oidc` ✅

Reclassified rather than rewired. The Authentik proxy outpost already
injects `Remote-User` / `Remote-Email` headers, and Firefly's
`LOGIN_PROVIDER=remote_user_guard` auto-creates the user from those
headers. This IS native SSO from the user's POV (no login screen,
identity flows from Authentik) — just not via OAuth2 protocol. The
new `header_oidc` doctrine bucket captures that distinction.

### β1.B — `node-red` → `native_oidc` ✅

First non-trivial native SSO upgrade — formerly `forward_auth`-only.
Implementation: `passport-openidconnect` pre-seeded into
`/data/node_modules` via `/data/package.json`; the strategy reads
`NODERED_OIDC_CLIENT_ID` + `NODERED_OIDC_CLIENT_SECRET` from env
(rendered by `nodered-base` plugin compose-extension). Toggle:
`nodered_native_oidc_enabled` (defaults `true`).

### β1.C — `metabase` ❌ deferred

Verification spike (2026-05-05) confirmed: Metabase OSS does NOT
expose `/admin/settings/authentication` OIDC options — paywall-gated
in Metabase Pro. Issue [#28195](https://github.com/metabase/metabase/issues/28195)
tracks community demand. No upstream PR will land this on the OSS
license; community fork would be required. Marked as permanently
proxy unless that landscape changes.

### β1.D — Doctrine bucket added ✅

The trichotomy (`native_oidc` / `header_oidc` / `forward_auth`) was
formalized in CLAUDE.md and pinned by anatomy gates
(`tests/anatomy/test_sso_doctrine.py`). The plugin schema accepts
exactly these three values; non-canonical labels are rejected.

## Still queued (post-β1 backlog)

These services have legitimate paths to native OIDC but require
either upstream changes or non-trivial scaffolding. Tracked in
[`upstream-pr-opportunities.md`](upstream-pr-opportunities.md).

- **calibre-web** — PR generic OIDC discovery to `cps/oauth.py`
- **code-server (LSIO)** — PR LSIO Dockerfile to forward Coder `--auth oauth-proxy` flags
- **ntfy** — PR OIDC verifier to `auth/auth_user.go` (maintainer indicated openness)
- **firefly post-β1.A** — env-driven OIDC PR upstream would let us drop the REMOTE_USER guard
- **paperclip** — upstream needs an OIDC scaffold first (our fork has none)
- **puter** — write an Authentik OIDC plugin (TS, plugin architecture)
- **wing** — Wing 2.0 work; replace proxy gate with native Nette\Security flow

## Permanently proxy (no semantic basis for native OIDC)

These services have no per-user state worth provisioning. The current
proxy-auth gate IS the right answer.

- **kiwix** — static content reader
- **mailpit** — dev SMTP capture
- **onlyoffice** — B2B JWT (DocServer is a render backend, not an end-user app)
- **spacetimedb** — DB binary protocol, no UI
- **influxdb (OSS)** — Enterprise-gated, not policy decision (could move if licensing pivots)
- **qdrant** — vector DB, no per-user state

For these, document the reason in the plugin manifest's
`_NOS_PROXY_REASON` sentinel so future audits don't try to "fix" them.
