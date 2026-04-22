# pazny.bookstack

BookStack wiki platform (library/book/chapter structure) as a Docker compose override in the nOS **b2b** stack.

- **Image**: `lscr.io/linuxserver/bookstack` (LinuxServer.io, ARM64 native)
- **Stack**: `b2b` (`docker compose -p b2b`)
- **Port**: `3013` (host -> container `:80`)
- **Domain**: `bookstack.{{ instance_tld | default('dev.local') }}` (Outline already holds `wiki.dev.local`)
- **DB**: MariaDB `bookstack` user/db, shared from the infra stack via `{{ stacks_shared_network }}`
- **Cache/Session/Queue**: Redis (auto-enabled when `redis_docker: true`)
- **SSO**: native OIDC via Authentik (env vars) — enabled by `install_authentik: true`

The role renders the compose override to `{{ stacks_dir }}/b2b/overrides/bookstack.yml`, which `tasks/stacks/stack-up.yml` picks up via `find` and passes as a `-f` flag to `docker compose up b2b`.

For the full integration checklist (install toggle, authentik_oidc_apps, mariadb_databases, nginx vhost, secrets) see `INTEGRATION.md`.
