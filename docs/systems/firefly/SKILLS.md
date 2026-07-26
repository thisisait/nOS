# Firefly III — Skills

> No external skill surface managed by nOS.

## No nOS-managed invocable surface

Firefly III in nOS exposes **no agent-invocable action that nOS authenticates**, for reasons read from source:

- **Access is a header guard, not a token.** Firefly uses `header_oidc` (`remote_user_guard`): the Authentik outpost injects a trusted identity header and Firefly auto-creates the account. There is no shared machine credential — an agent has no header to present, and the service is network-isolated off `shared_net` (SEC-02) specifically so nothing can forge one.
- **No nOS-provisioned API token.** Firefly III does ship a REST API at `/api/v1/*` (Bearer Personal Access Token or OAuth client). nOS mints and stores **neither** — `roles/pazny.firefly/tasks/post.yml` only waits on `/api/v1/about` and runs schema migrations; it creates no token. The only endpoint touched from source is the unauthenticated readiness probe, not an agent action.

To make Firefly agent-drivable, an operator would create a Personal Access Token in Firefly's Profile → OAuth and store it deliberately; this file should then be rewritten with the real token location and the specific `/api/v1/*` calls in use. Documenting a callable endpoint before that credential exists would be a confident-but-wrong answer — omitted on purpose.
