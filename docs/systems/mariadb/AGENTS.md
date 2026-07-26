# MariaDB — Agent Definition

## MariaDBSubstrate

**System:** MariaDB (`nos.infra.mariadb`, infra stack)
**Bind:** `127.0.0.1:3306` — loopback only, no domain, no SSO
**Role:** Passive relational datastore. Not directly agent-driven; consuming services own its rows.

### Context

- Image `mariadb:11.8.8`; container `infra-mariadb-1`; reachable in-cluster as `mariadb:3306`.
- Root credential: `mariadb_root_password` = `{global_password_prefix}_pw_mariadb`.
- Data in Docker named volume `mariadb_data` (VirtIOFS-crash avoidance); not host-browsable.
- No HTTP API. No OIDC. Auto-enabled when a MariaDB-backed consumer is toggled on.

### Capabilities

- None invocable over an API. An agent interacts with MariaDB only indirectly — through the consuming service's own surface — or, for operator-supervised maintenance, via `docker exec` SQL and the `upgrades/mariadb.yml` recipe.

### Liveness

`docker exec infra-mariadb-1 healthcheck.sh --connect` → exit `0`.

### Skills Reference

See [SKILLS.md](SKILLS.md) — there is no external skill surface, and why.
