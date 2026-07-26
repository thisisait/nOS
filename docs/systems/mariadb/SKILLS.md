# MariaDB — Skills

> **No external skill surface.** MariaDB is a headless TCP database, not an invocable HTTP service. There are deliberately no `**Trigger:**` skill nodes here.

## Why there are no skills

MariaDB exposes only the MySQL wire protocol on `127.0.0.1:3306`, bound to loopback. It has no REST/HTTP API, no dashboard, and no user-facing action an agent could invoke by calling an endpoint. Every mutation is a SQL statement issued by a consuming service (WordPress, Nextcloud, FreeScout, BookStack) over its own DSN, or by an operator at a shell. Inventing "skills" here would fabricate endpoints that do not exist — the exact failure this doc set removes.

## Operator access (informational, not an agent skill)

Direct SQL access is via the container shell, using the root credential `{global_password_prefix}_pw_mariadb`:

```bash
docker exec -it infra-mariadb-1 mariadb -uroot -p<password>
```

## Liveness (informational)

The manifest health probe is an exec, not an API call:

```bash
docker exec infra-mariadb-1 healthcheck.sh --connect
```

Exit code `0` means the server is accepting connections.
