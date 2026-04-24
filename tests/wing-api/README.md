# Wing State & Migration Framework — tests (agent 7)

Standalone PHP assertion scripts (no PHPUnit dependency). Each file can run
as `php tests/wing-api/<file>.php` and exits 0 on success, non-zero on
failure.

Prerequisites:

- `php` >= 8.3 (matches composer.json constraint)
- `ext-sqlite3` and `ext-pdo_sqlite`
- `ext-curl` (BoneClient uses it, though these tests only hit its guards)

Run all tests:

```bash
./tests/wing-api/run-all.sh
```

Each test creates a throwaway temp SQLite DB (not the production
`data/wing.db`). The schema is bootstrapped from
`files/project-wing/bin/init-db.php` + `db/schema-extensions.sql`.
