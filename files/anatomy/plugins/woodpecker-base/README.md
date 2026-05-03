# woodpecker-base — service plugin (DRAFT)

> **Status:** research draft, 2026-05-03 evening. **NOT loaded by anything.**
> First **tune-and-thin** harvest pilot per `docs/active-work.md` — smaller
> than A6.5 Grafana, used to validate the harvest workflow on a contained
> target before tackling the bigger pilot.

## Purpose

Capture the post-Q shape of the Woodpecker wiring: tendons (anatomy
autowiring — GDPR, Wing /hub card, notifications) and vessels (infra
wiring — Gitea OAuth2, security-hardened compose env, extra_hosts).

The role `pazny.woodpecker` will eventually keep ONLY install-internal
responsibilities (data dirs, base compose with image+ports+volumes); every
cross-service env var and the `debug:` Gitea-OAuth2-setup task become this
plugin's `compose_extension` + `gitea_oauth2` blocks.

## What this draft delivers

1. **Plugin manifest** (`plugin.yml`) — captures all wiring blocks per the
   schema referenced from `files/anatomy/docs/plugin-loader-spec.md`.
2. **Compose-extension template** (`templates/woodpecker-base.compose.yml.j2`)
   — carries the security-hardened env block, including the **REM-002**
   trusted-repos / privileged-plugins gate.
3. **Harvest map** (bottom of `plugin.yml`) — table of "today's surface →
   block in this manifest", so the future Track Q sweep that converts the
   draft into a real plugin has a checklist to walk.

## What it does NOT deliver yet

- **No loader integration.** The plugin loader (A6 foundation) currently
  only records intent for `render_compose_extension` and friends — it
  doesn't actually render. A6.5 (Grafana pilot) will make those side
  effects real; once that lands, this manifest becomes loadable too.
- **No live REM-002 hardening.** That ships separately as a direct edit
  to `roles/pazny.woodpecker/templates/compose.yml.j2` so the protection
  takes effect immediately, not gated on A6.5. The plugin manifest above
  documents the *eventual* home of the same env block.
- **No tests yet.** A6.5 doctrine work will define the canonical plugin
  test shape; this draft predates that and gets tests added in the
  Track Q sweep.

## REM-002 details

Five env vars carry the hardening (all live in the compose-extension
template):

| Var | Value | Defends against |
|---|---|---|
| `WOODPECKER_OPEN` | `false` | Anonymous account registration. |
| `WOODPECKER_REPO_OWNERS` | `gitea_admin_user` (default) | Any authenticated Gitea user triggering pipelines on their own fork — pipeline-as-RCE on the host. |
| `WOODPECKER_PLUGINS_PRIVILEGED` | `""` (empty allowlist) | Plugins requesting `privileged: true` containers (effectively root-on-host). Default is already empty in v3, but explicit pinning prevents silent regression. |
| `WOODPECKER_AUTHENTICATE_PUBLIC_REPOS` | `false` | Forked-PR pipelines from unaffiliated contributors. |
| `WOODPECKER_PROMETHEUS_AUTH_TOKEN` | derived from `global_password_prefix` | Future alloy scrape land-without-restart. |

The first four close REM-002. The fifth is forward-prep for Track Q1
(observability self-metrics).

## Reading order for the next agent

1. `files/anatomy/plugins/grafana-base/plugin.yml` — canonical shape.
2. This `plugin.yml` — concrete instance for a smaller, peer-OAuth-bound
   service (Gitea-bound, NOT Authentik-native — note the `mode: proxy_auth`
   in the `authentik:` block).
3. `files/anatomy/docs/role-thinning-recipe.md` — six-step recipe for
   converting this draft + the live role into a real thin-role + plugin.
   (Track Q work — not in this batch.)
