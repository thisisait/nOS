# portainer-base — service plugin (DRAFT) + REM-001 hardening

> **Status:** research draft, 2026-05-03 evening. **NOT loaded by anything.**
> Third tune-and-thin pilot per `docs/active-work.md`. Bundles **REM-001**
> (Group D CRITICAL) with the harvest of `roles/pazny.portainer/tasks/post.yml`
> — 272 LOC of API-driven post-setup, the largest in the repo.

## What landed LIVE (commit `feat(portainer): REM-001 hardening`)

The `tecnativa/docker-socket-proxy` already mediated `/var/run/docker.sock`
access, but its API surface for Portainer used to grant every Docker
Swarm flag plus `SYSTEM` plus `EXEC` plus `DISTRIBUTION`. REM-001's
"limit API surface" requirement is now satisfied by trimming the proxy
env in `templates/stacks/infra/docker-compose.yml.j2`:

| Flag | Before | After | Reason |
|---|---|---|---|
| `NODES` | 1 | (removed) | Swarm-only; nOS doesn't run Swarm |
| `PLUGINS` | 1 | (removed) | Swarm plugin manager; not used |
| `SECRETS` | 1 | (removed) | Swarm secrets; not used |
| `CONFIGS` | 1 | (removed) | Swarm configs; not used |
| `SWARM` | 1 | (removed) | Swarm cluster ops; not used |
| `SYSTEM` | 1 | (removed) | Daemon-level ops (df, prune); doesn't justify the surface |
| `EXEC` | 1 | toggle (`portainer_socket_proxy_can_exec`, default true) | Portainer web shell — RCE surface if compromised |
| `DISTRIBUTION` | 1 | toggle (`portainer_socket_proxy_can_distribution`, default true) | Registry pull from UI — token leak surface |
| `POST` | 1 | 1 (kept) | Container start/stop/restart |
| `BUILD` | 1 | 1 (kept) | Image build from Dockerfile |
| `CONTAINERS/IMAGES/NETWORKS/VOLUMES/SERVICES/TASKS/INFO/EVENTS/VERSION` | 1 | 1 (kept) | Read paths — Portainer UI navigation |

Operators security-sensitive can flip both toggles to `false` in
`config.yml` to fully close REM-001:

```yaml
portainer_socket_proxy_can_exec: false
portainer_socket_proxy_can_distribution: false
```

Trade-off: loses Portainer's container web shell + image-pull UI.
Container start/stop and image build still work.

## What's in the plugin draft (post-Q target)

The 272-LOC `roles/pazny.portainer/tasks/post.yml` is one big sequence
of HTTP API calls to localhost:9002. Plugin manifest captures it as a
declarative `api_calls:` block with per-call `when:` guards mirroring
today's idempotent shape:

| Phase | Tasks today (count) | Plugin block |
|---|---|---|
| 1: Admin bootstrap | 3 (wait_api + check + create) | `api_calls` ids `wait_api_ready`, `check_admin_exists`, `create_admin` |
| 1: Password reconverge | 4 (login current + login previous + PUT passwd + status) | `api_calls` ids `login_current_password`, `login_previous_password`, `reconverge_password` |
| 2: OAuth2 setup | 3 (get token + PUT settings + verify) | `api_calls` ids `get_admin_token`, `configure_oauth2` |
| 3: apps endpoint | 3 (list + register + status) | `api_calls` ids `list_endpoints`, `register_apps_endpoint` |

Plus the standard tendons (GDPR row, Wing /hub card, notifications) and
vessels (compose-extension target, OAuth2 vessel, conductor drift alarm).

## Notable design choices

- **`api_calls:` is a sequenced declarative DSL**, not a generic raw HTTP
  list. Each entry has `id`, `when:` (optional), `register:`, and
  `auth_token_from:` so loader can chain calls — same shape as Ansible's
  `uri:` module without the role boilerplate.
- **REM-001 trim lives in `templates/stacks/infra/docker-compose.yml.j2`
  TODAY**, not in this plugin's `compose_extension`. That's intentional:
  the trim must apply even when this plugin doesn't load (pre-A6.5). The
  manifest's `compose_extension` block is the post-Q target home — when
  loader is real, the trim moves OUT of base infra into the plugin so a
  Portainer-less install gets a tighter default.
- **Conductor drift alarm** (post-A8) is reserved in `notification:` —
  conductor will diff the running proxy env block against the REM-001
  baseline on a schedule and alert if any of the trimmed flags ever
  silently come back. Closes the "REM-001 fix could regress on a future
  base-template edit" failure mode.

## Two-blank gotcha

Same shape as Qdrant: Portainer admin password reconverge runs in
`post.yml` AFTER compose-up. If `portainer_admin_password` is rotated
mid-run via `global_password_prefix` change, the first blank's running
container may briefly auth-deny until the reconverge phase completes.
Operators see "401 invalid credentials" in Portainer UI for ~30s on
first blank with rotated prefix; second `ansible-playbook main.yml -K`
without `blank=true` confirms reconvergence persisted.
