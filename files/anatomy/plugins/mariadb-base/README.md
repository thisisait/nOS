# mariadb-base

Wiring layer for the pazny.mariadb role. Headless MySQL-protocol substrate in
the infra compose stack — backs WordPress, Nextcloud, FreeScout, BookStack and
any other MariaDB-backed consumer. No app-level OIDC, no Wing /hub card.
Activates when `install_mariadb: true`. Data lives in the named volume
`mariadb_data` (not a host bind-mount) to dodge the Apple Silicon VirtIOFS
InnoDB FK-ALTER crash class. Q3 batch.
