# gitea-base

**Status: SCAFFOLD (U8, 2026-05-04).** Declares the contract for Q2 native-OIDC
API wiring. The loader does not yet have a `replay_api_calls` runner — full
execution lands in **Phase 2 C5**. Until then, `roles/pazny.gitea/tasks/post.yml`
+ `tasks/stacks/authentik_service_post.yml:1-79` remain the live wiring path.

## What this plugin captures

- **Admin bootstrap (CLI):** `gitea admin user create` first-run, then
  `gitea admin user change-password` reconverge on every run. Mirrors
  `roles/pazny.gitea/tasks/post.yml:13-71`.
- **Authentik OIDC OAuth-source registration (REST):**
  `POST /api/v1/admin/identity-providers` (create) or `PATCH …/{id}` (update).
  Mirrors `tasks/stacks/authentik_service_post.yml:1-79`.

## Files

- `plugin.yml` — manifest with `authentik:` block (tier=2 manager, RBAC) and
  `lifecycle.post_compose: replay_api_calls: hooks/post_compose.yml`.
- `hooks/post_compose.yml` — declarative API-call sequence.
- `manifest.fragment.yml` — Phase 2 C2 merge target into `state/manifest.yml`.

## Phase plan

| Phase | What lands |
|-------|------------|
| **U8 (now)** | Manifest + hook sequence + GDPR row + `ui-extension.hub_card`. Loader skips unknown lifecycle entries gracefully. |
| **C1** | Drop the central `authentik_oidc_apps` Gitea entry from `default.config.yml` once authentik-base aggregator picks up this plugin's `authentik:` block. |
| **C2** | Operator merges `manifest.fragment.yml` into `state/manifest.yml`. |
| **C5** | Plugin-loader gains `replay_api_calls` runner + e2e validation against a live Gitea+Authentik pair. Role-side post.yml + service-post slice retire. |

## RBAC tier

`tier: 2` (manager) per `CLAUDE.md` "RBAC" section: Gitea is in the manager
group set alongside GitLab / n8n / ERPNext / FreeScout.
