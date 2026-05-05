# Upstream PR Opportunities — FOSS contributions to drop local auth hacks

> Companion to `docs/native-sso-survey.md`. For every nOS service that
> stays in `forward_auth` (or `header_oidc`) mode purely because the
> upstream FOSS doesn't ship native OIDC support, this doc captures
> the **specific upstream change** that would let nOS flip the plugin
> to `native_oidc`.
>
> Long-term goal: contribute upstream rather than maintain local
> sidecars / forks / config workarounds.

## Table of opportunities

| Service | Upstream | Today (nOS mode) | What's needed upstream | Effort | Filed |
|---|---|---|---|---|---|
| **calibre-web** | janeczku/calibre-web | `forward_auth` | Generic OIDC discovery in `cps/oauth.py` (today only Github + Google fixed clients). PR adds `OAUTH_CLIENT_ID/SECRET/ISSUER` env trio, falls back to Github/Google as today. | Medium (Python, OAuthlib) | TODO |
| **uptime-kuma** | louislam/uptime-kuma | `forward_auth` | v2 already has OIDC behind a feature flag. Upstream PR not needed — wait for v2 stable, then bump nOS image + add env block. | Low (just await release) | n/a |
| **ntfy** | binwiederhier/ntfy | `forward_auth` | Add OIDC verifier to `auth/auth_user.go` (today only basic auth + tokens). Maintainer has stated OIDC is on the roadmap. | High (Go, custom auth) | TODO |
| **mailpit** | axllent/mailpit | `forward_auth` | Mailpit is a dev SMTP capture tool — adding multi-user OIDC is out of scope upstream. **Stay proxy permanently.** | n/a | n/a |
| **kiwix** | kiwix/kiwix-tools | `forward_auth` | Kiwix is a static content reader; no per-user state. **Stay proxy permanently.** | n/a | n/a |
| **onlyoffice** | ONLYOFFICE/DocumentServer | `forward_auth` | DocServer is a render backend, not an end-user app — JWT server-to-server is the right contract. **Stay proxy permanently.** | n/a | n/a |
| **influxdb** (OSS) | influxdata/influxdb | `forward_auth` | OIDC is gated behind Enterprise license. Probably won't change without a licensing pivot. **Stay proxy** unless we accept the dependency on Enterprise. | n/a | n/a |
| **code-server** | coder/code-server (LSIO image) | `forward_auth` | Coder OSS supports OAuth proxy via env (`AUTH=*`); LSIO image strips that. PR to LSIO build args to forward `--auth oauth-proxy --oauth-...` flags. | Medium (Dockerfile) | TODO |
| **paperclip** | paperclipai/paperclip (own fork) | `forward_auth` | Native OIDC scaffold already in role (BetterAuth genericOAuth, gated by `paperclip_native_oidc_enabled=false`). Need to upstream a recipe + flip default. | Low (we own the fork) | TODO |
| **puter** | HeyPuter/puter | `forward_auth` | Puter has plugin architecture; need to write an Authentik OIDC plugin (or extend the OAuth plugin to read OIDC discovery URL). | High (TS / plugin) | TODO |
| **metabase** (OSS) | metabase/metabase | `forward_auth` | Generic OAuth login is Pro-tier feature (issue #28195 tracks community demand). Won't move soon. **Stay proxy** unless community fork emerges. | n/a | n/a |
| **spacetimedb** | clockworklabs/SpacetimeDB | `forward_auth` | Binary protocol; no end-user web UI. No OIDC needed. **Stay proxy permanently.** | n/a | n/a |
| **firefly** (post-β1.A) | firefly-iii/firefly-iii | `header_oidc` | v6+ has OIDC client mode but it's `auth.json`-file-driven (not env). Upstream PR adding `LOGIN_PROVIDER=oidc` + `OIDC_DISCOVERY_URL` env trio would let us drop the REMOTE_USER guard. | Medium (PHP) | TODO |

## How to track filing

When we file an upstream issue/PR, replace **TODO** in the `Filed` column
with the URL. After the PR lands and the new release ships:

1. Bump the image tag in `roles/pazny.<service>/defaults/main.yml`.
2. Flip the plugin's `mode:` to `native_oidc` (or `header_oidc` → `native_oidc`).
3. Add the OIDC env block to the role's compose template.
4. Update the entry above to ✅ + the release version.
5. Move the row to a "Closed" section.

## Permanently-proxy services

Some services have **no semantic basis** for native OIDC:

- **kiwix** — static content
- **mailpit** — dev SMTP capture
- **onlyoffice** — DocServer (B2B JWT)
- **spacetimedb** — DB binary protocol
- **influxdb (OSS)** — Enterprise-gated, not policy

For these, `forward_auth` is the **correct, final** mode. Document the
reason in the plugin manifest's `_NOS_PROXY_REASON` sentinel so future
audits don't try to "fix" them.
