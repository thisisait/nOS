# Native SSO Survey — proxy-auth services (β work, 2026-05-05)

> Companion to D1 (aggregator parity). Audits which currently-proxy-auth
> services in nOS could be upgraded to **native OIDC** with Authentik —
> giving operators true SSO (auto-provisioned user accounts + role
> mapping inside the service) instead of just access control at the
> outpost.
>
> Source of truth for "currently proxy": `default.config.yml`
> `authentik_oidc_apps` entries with `type: "proxy"`.

## Verdict matrix

| Service | Image | Upstream OIDC | Cost | Recommend |
|---|---|---|---|---|
| **uptime-kuma** | `louislam/uptime-kuma:1` | v1.x: NO. v2.x beta: YES (env-driven OIDC) | Bump to v2 when stable + env block | **Defer** — wait for v2 stable |
| **calibre-web** | `lscr.io/linuxserver/calibre-web` | Native OAuth2 (Github/Google only, no generic OIDC) | LSIO image patch needed | **Stay proxy** |
| **kiwix** | static reader | NO auth model upstream | n/a | **Stay proxy** |
| **paperclip** | `ghcr.io/paperclipai/paperclip` | Custom; check our fork | unknown | **Investigate (1 hr)** |
| **puter** | `nos/puter` (our build) | Plugin-based; needs a Puter OIDC plugin | High (write a Puter plugin) | **Defer** — out of D1 scope |
| **wing** | host launchd | Native OIDC (built-in Nette\Security plus our wing-base proxy gate today) | Wing app code change | **Defer** — Wing 2.0 work |
| **code-server** | `lscr.io/linuxserver/code-server` | NO direct OIDC (only basic password). LSIO doesn't ship OIDC. | Need a sidecar (oauth2-proxy) | **Stay proxy** |
| **ntfy** | `binwiederhier/ntfy` | NO native OIDC (basic auth + tokens only) | n/a | **Stay proxy** |
| **nodered** | `nodered/node-red:4.x` | Yes via `node-red-contrib-auth-keycloak` or custom strategy in settings.js | Medium — settings.js patch + secret env | **Candidate (β1)** |
| **firefly** | `fireflyiii/core:6.x` | Native OIDC since v5.6 — env-driven (`STATIC_CRON_TOKEN`, `LOGIN_PROVIDER=remote_user_guard` already used; OIDC mode via `REMOTE_USER` headers OR full OIDC via `LOGIN_PROVIDER=eloquent` + custom IDP) | Low — env block | **Candidate (β1)** |
| **influxdb** | `influxdb:2.7` | InfluxDB OSS 2.x: NO native OIDC (Cloud only). Enterprise: yes. | n/a for OSS | **Stay proxy** |
| **onlyoffice** | `onlyoffice/documentserver:9.x` | JWT-based (server-to-server only); no end-user OIDC | n/a | **Stay proxy** |
| **mailpit** | `axllent/mailpit` | Dev tool, basic auth only | n/a | **Stay proxy** |
| **metabase** | (already configured native, mis-marked proxy?) | Native OIDC (Pro) / OAuth (free) | Already done in role | **Investigate (1 hr)** — central says proxy but redirect_uri suggests native |
| **spacetimedb** | DB; not user-facing | n/a | n/a | **Stay proxy** (or skip auth) |

## Concrete β1 targets (recommended)

These three have **clean upstream OIDC support** and small implementation cost:

### β1.a — `firefly-iii` native OIDC

- Image already on `version-6.2.21` (post-5.6 OIDC-capable).
- Today: `LOGIN_PROVIDER=remote_user_guard` (header-based via Authentik
  outpost). Migrate to true OIDC by setting:
  ```yaml
  LOGIN_PROVIDER: eloquent           # builtin user table
  AUTHENTIK_OIDC_DISCOVERY_URL: ...  # NB: Firefly doesn't ship native OIDC env vars yet
  ```
- **Caveat:** Firefly's "OIDC" is actually OAuth2-server mode (Firefly
  *acts as* an OAuth provider). True OIDC consumer mode is via
  `auth.json` Sanctum config, not env. **Verdict: not as easy as it
  looks. Mark as research-needed (1 hr) before promoting.**
- Realistic path: extend the existing `remote_user_guard` setup —
  Authentik outpost already injects `Remote-User` / `Remote-Email`
  headers, and Firefly auto-creates the user. This IS native SSO from
  the user's POV (no Firefly login screen, identity from Authentik) —
  just not via OAuth2 protocol. The current "proxy" classification in
  central undersells it; recommend **renaming `firefly` to
  `mode: header_oidc`** (a new doctrine bucket) rather than rewiring.

### β1.b — `node-red` native OIDC

- Node-RED's `settings.js` accepts a `passport`-strategy block:
  ```js
  adminAuth: {
    type: "strategy",
    strategy: {
      name: "openidconnect",
      label: "Sign in with Authentik",
      strategy: require("passport-openidconnect"),
      options: {
        issuer: "https://auth.<tld>/application/o/nodered/",
        authorizationURL: ".../authorize/",
        tokenURL: ".../token/",
        userInfoURL: ".../userinfo/",
        clientID: "nos-nodered",
        clientSecret: "...",
        callbackURL: "https://nodered.<tld>/auth/strategy/callback",
        scope: "openid profile email"
      },
      verify: function(token, profile, done){ done(null, profile) }
    },
    users: ...
  }
  ```
- Cost: render `settings.js` from a template, mount via `-v`, install
  `passport-openidconnect` in the container OR a sidecar.
- Image `nodered/node-red:4.x` ships passport built-in; we'd need to
  add `passport-openidconnect` via a pre-start `npm install --prefix
  /data` step.
- Realistic estimate: **~2 hr** + 1 blank verify.
- **Verdict: viable β1 target.**

### β1.c — `metabase` native OIDC (verify existing)

- Central says `type: "proxy"` AND has redirect_uri `/auth/sso/oidc`.
  Contradiction. The role's compose.yml.j2 grep found NO OIDC env.
  But Metabase 0.50+ supports `MB_JWT_*` and `MB_OIDC_*` envs
  (Enterprise feature, possibly behind a license).
- Realistic next step: **30-min verification spike** — does our running
  Metabase have the OIDC option in /admin/settings/authentication, or
  is that license-gated?
- If OSS: viable β1 target (~1 hr env block + role tweak).
- If license-gated: stay proxy, fix central to remove the misleading
  redirect_uri.

## Concrete β1 NON-targets

These should **explicitly stay proxy** (document + close the door):
- `kiwix` — no upstream auth model
- `mailpit` — dev tool, basic auth only
- `ntfy` — token-based, no OIDC roadmap
- `onlyoffice` — JWT server-to-server only
- `influxdb` (OSS) — Enterprise-only OIDC
- `code-server` (LSIO image) — no upstream OIDC, needs sidecar (out of scope)
- `calibre-web` — only Github/Google OAuth2, no generic OIDC

For these, **the current proxy-auth gate IS native SSO** from the
operator's POV: Authentik authenticates the user, sets a cookie, the
service trusts the upstream and serves content. There's no "user
account inside the service" to provision because there's no per-user
state worth provisioning.

## Recommended action sequence

1. **Re-classify proxy-only-because-no-OIDC services** — add a
   `mode: header_oidc` bucket to the plugin schema (Authentik proxy
   outpost forwards `Remote-User`/`Remote-Email` headers; service
   auto-creates user from header). Apply to: `firefly`, `paperclip`,
   `wordpress` (it has both modes today). This makes the plugin
   metadata semantically correct without changing runtime behaviour.
2. **β1.b node-red** — implement true native OIDC via passport
   strategy (~2 hr).
3. **β1.c metabase verification spike** — 30 min; promote to β1
   target if OSS supports it, else mark "stay proxy" with reasoning.
4. **β1.a firefly** — research, then either implement true OIDC OR
   reclassify as `header_oidc` per #1.
5. **Defer to backlog:** uptime-kuma (await v2 stable), puter (write
   plugin), wing (Wing 2.0).

## Doctrine update needed

`CLAUDE.md` currently has a binary "Native OIDC vs Proxy auth" split.
β survey shows three real buckets:

- **`native_oidc`** — service consumes OIDC at app level (oauth2 / OIDC client)
- **`header_oidc`** — proxy outpost forwards trusted headers (user
  auto-provisioned in the service, but no OIDC client inside service)
- **`forward_auth`** — pure access gate, no per-user state in service

Today only the first two grant true SSO; the third grants access
control. Updating CLAUDE.md to surface the trichotomy is a D1.4 follow-up.
