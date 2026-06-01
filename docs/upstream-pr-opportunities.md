# Upstream PR Opportunities — FOSS contributions to drop local auth hacks

> Companion to [`native-sso-survey.md`](native-sso-survey.md). For every nOS
> service that stays in `forward_auth` (or `header_oidc`) mode purely because
> the upstream FOSS doesn't ship native OIDC support, this doc captures the
> **specific upstream change** that would let nOS flip the plugin to
> `native_oidc`.
>
> Long-term goal: contribute upstream rather than maintain local sidecars /
> forks / config workarounds.
>
> **Updated 2026-05-20** — post-β1 status pass.

## Table of opportunities

| Service | Upstream | Today's mode | What's needed upstream | Effort | Status |
|---|---|---|---|---|---|
| **calibre-web** | janeczku/calibre-web | `forward_auth` | Generic OIDC discovery in `cps/oauth.py` (today only Github + Google fixed clients). PR adds `OAUTH_CLIENT_ID/SECRET/ISSUER` env trio, falls back to fixed clients as today. | Medium (Python, OAuthlib) | TODO |
| **uptime-kuma** | louislam/uptime-kuma | `forward_auth` | v2 already has OIDC behind a feature flag. Upstream PR not needed — wait for v2 stable, then bump nOS image + add env block. Second-login today: local Kuma account → **needs-upstream** (await v2). | Low (just await release) | n/a — await release |
| **influxdb (OSS)** | influxdata/influxdb | `forward_auth` | OSS 2.x has no OIDC — auth is Enterprise/Cloud-gated. No upstream PR will land it on the OSS license; would move only on a licensing pivot. Second-login: local user DB → **needs-upstream** (shared operator credential behind the gate meanwhile). | n/a — license-gated | blocked (license) |
| **metabase (OSS)** | metabase/metabase | `forward_auth` | OAuth/SAML are paywall-gated in Metabase Pro ([#28195](https://github.com/metabase/metabase/issues/28195)). No upstream OSS PR path. Second-login: Metabase user dir → **needs-upstream** (shared operator account behind the gate meanwhile). | n/a — license-gated | blocked (license) |
| **ntfy** | binwiederhier/ntfy | `forward_auth` | Add OIDC verifier to `auth/auth_user.go` (today only basic auth + tokens). Maintainer has stated OIDC is on the roadmap. | High (Go, custom auth) | TODO |
| **code-server** | coder/code-server (LSIO image) | `forward_auth` | Coder OSS supports OAuth proxy via env (`AUTH=*`); LSIO image strips that. PR to LSIO build args to forward `--auth oauth-proxy --oauth-...` flags. Second-login: `HASHED_PASSWORD` prompt → eliminate via the PR **or** an oauth2-proxy sidecar (`needs-sidecar`). | Medium (Dockerfile) | TODO |
| **paperclip** | paperclipai/paperclip | `forward_auth` | Plugin manifest explicitly declares "no native OIDC support" today. Upstream needs an OIDC scaffold first (BetterAuth genericOAuth or trusted-header adapter) before nOS can flip the toggle. Second-login: better-auth session → `header-provision-patch`. | High (TS, app code) | TODO |
| **puter** | HeyPuter/puter | `forward_auth` | Puter has plugin architecture; need to write an Authentik OIDC plugin (or extend the OAuth plugin to read OIDC discovery URL). Second-login: Puter user dir → `needs-upstream`. | High (TS / plugin) | TODO |
| **openclaw** | pazny-develop/nOS (own gateway) | `forward_auth` | nOS-owned launchd Node.js LLM gateway authenticates with a static gateway token and has no path to consume the forwarded `X-Authentik-*` headers. Second-login: gateway token → `header-provision-patch` (teach the gateway to trust forward-auth headers / inject the token). Tier-1 admin-only, low urgency. | Medium (own JS) | TODO |
| **woodpecker** | woodpecker-ci/woodpecker | `forward_auth` (over Gitea-OAuth) | Already Authentik-rooted via Gitea native-OIDC, so there is no password second-login — only the intermediate Gitea OAuth consent click. Woodpecker server has **no** generic-OIDC and **no** trusted-proxy / `REMOTE_USER` backend (only forge OAuth), so the consent click cannot be dropped by config today. Eliminate via upstream adding a generic-OIDC or header-auth backend (`needs-upstream`). | High (Go, auth backend) | TODO |
| **firefly** (post-β1.A) | firefly-iii/firefly-iii | `header_oidc` | v6+ has OIDC client mode but it's `auth.json`-file-driven (not env). Upstream PR adding `LOGIN_PROVIDER=oidc` + `OIDC_DISCOVERY_URL` env trio would let us drop the `REMOTE_USER` guard. | Medium (PHP) | TODO |

## Closed (no PR needed)

| Service | What changed | Date |
|---|---|---|
| **nodered** | β1.B shipped — `passport-openidconnect` wired into `/data/settings.js::adminAuth.strategy` via `nodered-base` plugin compose-extension. No upstream PR needed; the strategy mechanism was already in Node-RED 4.x. | 2026-05-05 |
| **firefly** | β1.A shipped — reclassified `header_oidc` (Authentik outpost headers + `LOGIN_PROVIDER=remote_user_guard`). True SSO from user POV without OAuth2 protocol. | 2026-05-05 |

## Permanently-proxy services (no semantic basis for native OIDC)

These services have **no per-user state worth provisioning** — `forward_auth`
is the correct, final mode.

- **kiwix** — static content reader
- **mailpit** — dev SMTP capture, no multi-user model
- **onlyoffice** — B2B JWT (DocServer is a render backend, not end-user)
- **spacetimedb** — DB binary protocol, no UI
- **qdrant** — vector DB, no per-user state
- **snappymail** — webmail; identity is IMAP-account-determined (Stalwart), not Authentik. SSO for IMAP does not exist → by-design proxy.

> **influxdb (OSS)** and **metabase (OSS)** are NOT in this list — they have a
> per-user model and a real (license-gated) OIDC path, so they live in the table
> above as `blocked (license)` upstream-waits, not as permanently-proxy.

Document the reason in the plugin manifest's `_NOS_PROXY_REASON` sentinel so
future audits don't try to "fix" them.

## How to track filing

When we file an upstream issue/PR, replace **TODO** in the `Status` column
with the URL. After the PR lands and the new release ships:

1. Bump the image tag in `roles/pazny.<service>/defaults/main.yml`.
2. Flip the plugin's `mode:` to `native_oidc` (or `header_oidc` → `native_oidc`).
3. Add the OIDC env block to the plugin's `*-base.compose.yml.j2` compose-extension.
4. Move the row from "Table of opportunities" to "Closed" with date + change summary.
