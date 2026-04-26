# pazny.spacetimedb

[SpacetimeDB Standalone](https://spacetimedb.com) as a Docker service inside the
nOS `infra` compose stack.

## License (BSL 1.1)

SpacetimeDB is published under the **Business Source License 1.1** by Clockwork
Laboratories, Inc. The Additional Use Grant of the [bundled
LICENSE.txt](https://github.com/clockworklabs/SpacetimeDB/blob/master/LICENSE.txt)
permits use as long as:

- Your application or service runs at most **one SpacetimeDB instance in
  production** (dev / staging instances are not counted).
- You do **not** offer it as a "Database Service" — i.e. let third parties
  outside your employees / contractors create tables whose schemas they
  control.

The license auto-converts to **AGPLv3 with a linking exception** on
**2031-03-20**, after which the above limits no longer apply.

For the nOS internal-SaaS use case (employees + contractors of the operator,
single production node, no multi-tenant DBaaS) BSL is satisfied.

## What this role does

`tasks/main.yml` (compose render):

1. Ensures `{{ spacetimedb_data_dir }}` and `{{ spacetimedb_keys_dir }}` exist.
2. **Generates an ECDSA P-256 keypair** (`id_ecdsa` / `id_ecdsa.pub`) if
   missing. Rotating this keypair would orphan every existing identity and
   database, so the role only ever generates it once.
3. Renders the compose override fragment to
   `{{ stacks_dir }}/infra/overrides/spacetimedb.yml`. `tasks/stacks/core-up.yml`
   collects it via `find` and passes it as an additional `-f` flag to
   `docker compose up infra --wait`.

`tasks/post.yml` (onboarding, runs after `infra` is up):

1. Health-checks `http://127.0.0.1:{{ spacetimedb_port }}/v1/ping`.
2. Installs the `spacetime` CLI on the host (curl install script) when
   `spacetimedb_install_host_cli: true` (default).
3. Registers a CLI server alias `nos` pointing at the local instance and
   marks it as default.
4. Prints an onboarding summary with the next steps for the operator.

The role intentionally does **not** auto-publish a module — publishing
requires a WASM artifact, which is project-specific. The role's job ends at
"infrastructure ready"; the operator owns their first module.

## Authentication model

SpacetimeDB has no admin login UI and no admin password. Authentication is
entirely JWT-based:

- **Server-issued tokens** — SpacetimeDB signs tokens with the local ECDSA
  keypair this role generates. The host `spacetime` CLI uses these tokens to
  publish modules.
- **External OIDC tokens** — clients can pass any well-formed OIDC ID token
  (e.g. issued by the nOS Authentik instance at `{{ spacetimedb_oidc_issuer }}`)
  via the `Authorization: Bearer …` header. SpacetimeDB validates the JWT
  against the issuer's JWKS endpoint on demand.

There is no server-side "trusted issuer" allowlist. Trust is enforced **per
module**: your reducer reads `ctx.sender.identity` (a deterministic hash of
`iss` + `sub`) and decides what to do. See
[Authentication | SpacetimeDB docs](https://spacetimedb.com/docs/core-concepts/authentication/).

## SSO with Authentik

`default.config.yml` registers a proxy-auth Authentik application for
`spacetime.<tld>` so administrative access to the API endpoint goes through
SSO. CLI tooling on the host bypasses the proxy by hitting `127.0.0.1:{{
spacetimedb_port }}` directly. Tier 1 (`nos-providers` + `nos-admins`) only.

## RBAC

There is no native RBAC in SpacetimeDB. Three layers cover the gap:

| Layer | What it gates | Where |
|---|---|---|
| Network | who can reach the API endpoint at all | nginx (forward_auth via Authentik) |
| Module ownership | who can publish / modify modules | `spacetime` CLI on the host (server-issued JWT) |
| Per-row / per-reducer | who can read / write specific tables | inside your WASM module — `ctx.sender.identity` checks |

## Variables

| Variable | Default | Description |
|---|---|---|
| `spacetimedb_version` | `latest` | `clockworklabs/spacetime` image tag — pin for production |
| `spacetimedb_port` | `3030` | Host port → container 3000 |
| `spacetimedb_domain` | `spacetime.dev.local` | Public hostname (nginx vhost) |
| `spacetimedb_data_dir` | `$HOME/spacetimedb/data` | Persistent `/stdb` mount |
| `spacetimedb_keys_dir` | `$HOME/spacetimedb/keys` | ECDSA keypair, mounted read-only into `/etc/spacetimedb` |
| `spacetimedb_install_host_cli` | `true` | Install `spacetime` binary on host via curl install script |
| `spacetimedb_oidc_issuer` | `https://{{ authentik_domain }}/application/o/spacetimedb/` | Surfaced as env var for client modules |
| `spacetimedb_dev_db` | `dev` | Logical name printed in the post-start hint |

## Lifecycle

```bash
# Enable, full reconverge
ansible-playbook main.yml -K --tags "spacetimedb"

# Bring up just the infra stack with SpacetimeDB
ansible-playbook main.yml -K --tags "core,spacetimedb"

# Restart only this service (notified handler)
docker compose -f ~/stacks/infra/docker-compose.yml -p infra restart spacetimedb
```

## Known constraints

- The Postgres wire protocol (`--pg-port 5432`) is **disabled** in this role
  to avoid a conflict with `pazny.postgresql`. Add `--pg-port <free-port>` to
  the compose `command:` if you need it.
- The JWT keypair is treated as **load-bearing data**: lose it and every
  identity / database becomes inaccessible. Back up `{{ spacetimedb_keys_dir }}`
  the same way you back up `{{ spacetimedb_data_dir }}`.
