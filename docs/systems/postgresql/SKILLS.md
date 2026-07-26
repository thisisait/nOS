# PostgreSQL — Skills

> **No external skill surface.** PostgreSQL is a headless TCP database, not an invocable HTTP service. There are deliberately no `**Trigger:**` skill nodes here.

## Why there are no skills

PostgreSQL exposes only the libpq wire protocol on `127.0.0.1:5432`, bound to loopback. It has no REST/HTTP API, no dashboard, and no user-facing action an agent could invoke by calling an endpoint. Every mutation is a SQL statement issued by a consuming service (Authentik, Outline, HedgeDoc, Miniflux, BookStack, Wing/Bone) over its own DSN, or by an operator at a shell. Inventing "skills" here would fabricate endpoints that do not exist.

## Operator access (informational, not an agent skill)

Direct SQL access is via the container shell, using the `postgres` superuser and credential `{global_password_prefix}_pw_postgresql`:

```bash
docker exec -it infra-postgresql-1 psql -U postgres
```

## Liveness (informational)

The manifest health probe is an exec, not an API call:

```bash
docker exec infra-postgresql-1 pg_isready -U postgres
```

Exit code `0` means the server is accepting connections.
