# Glasswing State & Migration Framework — tests (agent 7)

Standalone PHP assertion scripts (no PHPUnit dependency). Each file can run
as `php tests/glasswing-api/<file>.php` and exits 0 on success, non-zero on
failure.

Prerequisites:

- `php` >= 8.3 (matches composer.json constraint)
- `ext-sqlite3` and `ext-pdo_sqlite`
- `ext-curl` (BoxApiClient uses it, though these tests only hit its guards)

Run all tests:

```bash
./tests/glasswing-api/run-all.sh
```

Each test creates a throwaway temp SQLite DB (not the production
`data/glasswing.db`). The schema is bootstrapped from
`files/project-glasswing/bin/init-db.php` + `db/schema-extensions.sql`.
