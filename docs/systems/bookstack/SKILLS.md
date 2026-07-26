# BookStack — Skills

> No external skill surface managed by nOS.

## No nOS-managed invocable surface

BookStack in nOS has **no agent-invocable action** that nOS provisions or authenticates. There is intentionally nothing to call here, for concrete reasons read from source:

- **No bot account, no token file.** Unlike Grafana (which auto-creates an `openclaw-bot` service account and drops a token under `~/agents/tokens/`), the BookStack role and plugin provision no service account and no API token. `roles/pazny.bookstack/tasks/` has no post-start admin/token step.
- **Identity is per-user OIDC.** Access is `native_oidc` (Authentik client `nos-bookstack`, tier 3). Every principal authenticates interactively as themselves; there is no shared machine identity.
- **Upstream API exists but is un-wired.** BookStack does expose a REST API (`/api/*`, authenticated with a per-user `token_id:token_secret` minted in the user profile UI). nOS neither mints nor stores such a token, so no verified endpoint/credential can be documented here without inventing one.

To give an agent BookStack access, an operator would mint a per-user API token in BookStack and store it deliberately — at which point this file should be rewritten with the real, verified `token_id`/`token_secret` location and the specific `/api/*` endpoints in use. Until then, presenting a callable endpoint here would be a confident-but-wrong answer, which is worse than none.
