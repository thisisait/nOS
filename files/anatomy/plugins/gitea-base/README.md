# gitea-base

**Status: LIVE CONTRACT (U8 → C5, 2026-05-23).** Declares the contract for
Q2 native-OIDC API wiring. The loader now has a `replay_api_calls` runner;
`roles/pazny.gitea/tasks/post.yml` + `tasks/stacks/authentik_service_post.yml`
remain as parity fallback until one more idempotent live run proves the
plugin-only path.

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
| **U8** | Manifest + hook sequence + GDPR row + `ui-extension.hub_card`. |
| **C1** | Central `authentik_oidc_apps` entry retired; authentik-base aggregator picks up this plugin's `authentik:` block. |
| **C2** | Operator merges `manifest.fragment.yml` into `state/manifest.yml`. |
| **C5** | Plugin-loader gained `replay_api_calls`; role-side post.yml + service-post slice retire after final live parity gate. |

## RBAC tier

`tier: 2` (manager) per `CLAUDE.md` "RBAC" section: Gitea is in the manager
group set alongside GitLab / n8n / ERPNext / FreeScout.
