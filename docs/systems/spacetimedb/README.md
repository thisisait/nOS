# SpacetimeDB

> Realtime database where the stored procedures ARE the application: clients subscribe to queries over WebSocket and receive rows as they commit. BSL 1.1 — one production instance for internal use.

## Quick Reference

| | |
|---|---|
| **Host port** | `127.0.0.1:3030` → container `3000` (`spacetimedb_port`; 3030 to stay clear of Grafana's 3000) |
| **Stack** | `infra` |
| **Toggle** | `install_spacetimedb: false` (default.config.yml:533); excluded from `profiles/all-on.yml` |
| **Image** | `clockworklabs/spacetime:v2.7.0-hotfix3` (`spacetimedb_version`) |
| **Compose** | `~/stacks/infra/overrides/spacetimedb.yml` |
| **Data** | `spacetimedb_data_dir`; ECDSA keypair in `spacetimedb_keys_dir` |
| **Manifest node** | `nos.infra.spacetimedb` |

> **No `domain_var` in the manifest row, deliberately.** `domain_var` + `port_var` auto-derives a Traefik router, and `roles/pazny.traefik/vars/main.yml:43` says `spacetimedb: none  # binary protocol` while `files/anatomy/plugins/spacetimedb-base/plugin.yml:59` says `mode: forward_auth`. The row does not settle that contradiction; an operator does. `spacetimedb_domain` still exists and is what the hub card and the OIDC issuer use.

## Authentication

- **No admin UI, no passwords.** Identity is a JWT.
  - Server-issued tokens are signed by the local ECDSA keypair mounted into the container; the host `spacetime` CLI uses them to publish modules.
  - External OIDC tokens (e.g. Authentik) are validated against the issuer's JWKS. There is no server-side trusted-issuer list — trust is enforced *inside the module*, which reads `ctx.sender.identity` and the `iss` claim.
- **SSO bucket:** `forward_auth` per the plugin. See the edge note above.
- Postgres wire protocol (`--pg-port`) is deliberately NOT enabled, so 5432 stays with `pazny.postgresql`.

## Health Check

- `GET http://127.0.0.1:3030/admin` (plugin `wait_health`).

## Dependencies

- Traefik (edge), Authentik (token issuer, optional), host `spacetime` CLI when `spacetimedb_install_host_cli` is true.
