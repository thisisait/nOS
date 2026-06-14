# Restore runbook

Operator guide for the `restore` playbook tag. Pulls a dated backup from RustFS
and replays it into the running infra stack.

> **This is a destructive operation.** The playbook prompts for interactive
> confirmation before anything writes. There is no undo — take a fresh backup
> first if you are unsure.

---

## 1. When to use it

| Scenario | Restore? |
|---|---|
| Disaster recovery — host died, rebuilt from scratch | **Yes** — full restore. |
| Accidental `DROP DATABASE`, table wipe, or bad migration | **Yes** — partial restore of the affected DB. |
| Point-in-time test: "what did this dashboard look like last Tuesday?" | Use **test-restore on a coexistence track** (see §5), not a live restore. |
| Single user deleted a file in Nextcloud | **No** — use the app's trash / versioning. |
| You want to migrate to a new box | Use `tasks/export-state.yml` + `import-state.yml`, not `restore`. |

---

## 2. Prerequisites

- The `infra` stack must be running (`infra-mariadb-1`, `infra-postgresql-1`,
  etc.). `blank=true` wipes these, so run `ansible-playbook main.yml -K` first
  if you are restoring onto a freshly wiped host.
- `aws` CLI installed (it's part of the base `brew` bundle).
- RustFS reachable at `http://127.0.0.1:9010` and the `backups` bucket exists.
- `rustfs_access_key` / `rustfs_secret_key` in your `credentials.yml`.
- `backup_encryption_passphrase` in your `credentials.yml`. Nightly dumps are
  AES-256 client-side encrypted (objects carry a `.enc` suffix); the restore
  step auto-detects and decrypts them with this value. It **must** match the
  passphrase the backup ran with — a wrong/missing value fails the restore loud
  (no silent fallback). Legacy plaintext (`.sql.gz` without `.enc`) restores
  unchanged. `openssl` with `enc -pbkdf2` support must be on `PATH`.

---

## 3. List available backup dates

```bash
aws --endpoint-url http://127.0.0.1:9010 \
    --profile rustfs \
    s3 ls backups/
```

Or without a profile, inline creds:

```bash
AWS_ACCESS_KEY_ID=<rustfs_access_key> \
AWS_SECRET_ACCESS_KEY=<rustfs_secret_key> \
aws --endpoint-url http://127.0.0.1:9010 s3 ls backups/
```

Example output:

```
                           PRE 2026-04-18/
                           PRE 2026-04-19/
                           PRE 2026-04-20/
```

Peek inside a date:

```bash
aws --endpoint-url http://127.0.0.1:9010 s3 ls backups/2026-04-20/
```

Expected entries (each `.enc` when encryption is on — the default):

```
mariadb.sql.gz                 # mariadb-dump --all-databases
postgres.sql.gz                # pg_dumpall
volume-<name>.tar.gz           # Docker named volume(s), if any configured
dir-gitea.tar.gz               # host-bind git repos
dir-gitlab.tar.gz
dir-gitlab-config.tar.gz
wing-db.sql.gz                 # Wing SQLite store (sqlite3 .dump)
nos-state.tar.gz               # ~/.nos/{secrets,state}.yml  (restore GATED, see §4)
authentik-blueprints.json      # OIDC/flows/RBAC defs (live users are in the PG dump)
```

> The object stem (basename minus extension) IS the restore `source`. One fixed
> key per source per day — no timestamps. The backup ↔ restore naming contract
> is pinned by `tests/anatomy/test_backup_restore_contract.py`.

---

## 4. Restore commands

### Full restore (everything at that date)

```bash
ansible-playbook main.yml -K --tags restore \
    -e restore_date=2026-04-20
```

### Partial restore (pick the sources)

`restore_sources` is a comma-separated list. Match the filename **stem** (the
basename without the extension) or the full filename.

```bash
# just MariaDB + Postgres
ansible-playbook main.yml -K --tags restore \
    -e restore_date=2026-04-20 \
    -e restore_sources=mariadb,postgres

# a single volume / a host-bind dir (gitea repos) / the Wing store
ansible-playbook main.yml -K --tags restore \
    -e restore_date=2026-04-20 \
    -e restore_sources=volume-mariadb_data,dir-gitea,wing-db

# Authentik config only
ansible-playbook main.yml -K --tags restore \
    -e restore_date=2026-04-20 \
    -e restore_sources=authentik-blueprints
```

### Restoring `~/.nos` state (GATED — fresh-host DR only)

`nos-state` (encryption keys, tokens, `state.yml`) is **never restored by
default**: overwriting a live `secrets.yml` that has been re-keyed since the
backup would brick SSO. Opt in only on a true disaster-recovery onto a fresh
host:

```bash
ansible-playbook main.yml -K --tags restore \
    -e restore_date=2026-04-20 -e restore_state=true
```

### Verify the restore actually replayed

```bash
ansible-playbook main.yml --tags restore-verify
```

Asserts DB-count floors + Authentik user count + Wing rows — turns a "restore
reported ok" into a proven-good one.

### Skip the interactive prompt (CI / scripted recovery)

```bash
ansible-playbook main.yml -K --tags restore \
    -e restore_date=2026-04-20 \
    -e restore_auto_confirm=true
```

Use this only when the command runs inside a larger, already-approved automation
flow. A human-driven restore should always see the prompt.

### Dry run (safe — no writes)

```bash
ansible-playbook main.yml -K --tags restore --check \
    -e restore_date=2026-04-20
```

Validates inputs, lists the plan, downloads nothing, restores nothing.

---

## 5. Test-restore pattern (validate before overwriting prod)

Rather than restoring over production, use the **coexistence** framework to
spin up a parallel track of the affected service on a shifted port, point it
at the restored data, and verify everything before cutting over.

```bash
# 1. Provision a coexistence track for Postgres on a shifted port
ansible-playbook main.yml -K --tags coexistence -e coex_service=postgresql \
    -e coex_action=provision

# 2. Restore the dump into the coexistence track (not the live instance)
#    NOTE: coexistence containers are named infra-postgresql-coex-1; to restore
#    into them, manually pipe the dump:
aws --endpoint-url http://127.0.0.1:9010 \
    s3 cp s3://backups/2026-04-20/postgres.sql.gz - \
  | gunzip \
  | docker exec -i infra-postgresql-coex-1 psql -U postgres

# 3. Point a throwaway service (e.g. Metabase test instance) at the coex port
#    and verify. If good, cut over:
ansible-playbook main.yml -K --tags coexistence -e coex_service=postgresql \
    -e coex_action=cutover
```

See `files/anatomy/docs/coexistence-playbook.md` for the full framework.

---

## 6. What the playbook does (for auditors)

1. Validates `restore_date` is set and well-formed.
2. Lists `s3://backups/<date>/` via the RustFS S3 endpoint.
3. Filters that list by `restore_sources` (or takes everything).
4. Prompts the operator to confirm (`ansible.builtin.pause`).
5. Downloads every planned object to `~/restore-temp/<date>/`.
6. Decrypts any `.enc` object (resolves a `-pbkdf2`-capable openssl, mirror of
   the producer) → plaintext.
7. Per source:
   - `mariadb.sql.gz` → `gunzip | docker exec -i infra-mariadb-1 mariadb -uroot -p…`
   - `postgres.sql.gz` → `gunzip | docker exec -i infra-postgresql-1 psql -U postgres`
   - `volume-<name>.tar.gz` → stop consumers → wipe volume via alpine →
     `tar -xzf -` into volume → restart consumers
   - `dir-<name>.tar.gz` → resolve host target (`restore_dir_targets`) → stop
     consumers → `tar -xzf` into the bind dir → restart consumers
   - `wing-db.sql.gz` → stop Wing → snapshot current wing.db → `gunzip | sqlite3`
     rebuild → restart Wing
   - `nos-state.tar.gz` → **skipped unless `-e restore_state=true`** → extract `~/.nos`
   - `authentik-blueprints.json` → `POST /api/v3/managed/blueprints/` with the
     Authentik bootstrap bearer token
8. Re-runs `pazny.mariadb/tasks/post.yml` and `pazny.postgresql/tasks/post.yml`
   to re-seed databases, grants, and extensions that per-service roles expect.
9. Prints a summary: source, status, bytes restored, duration.

---

## 7. Post-restore verification checklist

Run these after the playbook finishes and before telling anyone "we're back."

### 7.1 Infra health probes

```bash
ansible-playbook main.yml --tags health
```

### 7.2 MariaDB row counts

```bash
# Databases present
docker exec infra-mariadb-1 mariadb -uroot -p"$MARIADB_ROOT_PASSWORD" \
    -e "SHOW DATABASES;"

# Spot-check a heavyweight table (example: WordPress)
docker exec infra-mariadb-1 mariadb -uroot -p"$MARIADB_ROOT_PASSWORD" \
    -e "SELECT COUNT(*) FROM wordpress.wp_posts;"
```

### 7.3 PostgreSQL row counts

```bash
docker exec infra-postgresql-1 psql -U postgres -c "\l"

# Authentik users
docker exec infra-postgresql-1 psql -U postgres -d authentik \
    -c "SELECT COUNT(*) FROM authentik_core_user;"
```

### 7.4 Web-app smoke tests

```bash
# SSO landing page
curl -skI https://auth.dev.local/ | head -1            # expect 200/302

# A couple of per-app landing pages
curl -skI https://git.dev.local/                       # Gitea
curl -skI https://cloud.dev.local/                     # Nextcloud
curl -skI https://grafana.dev.local/login              # Grafana
```

### 7.5 Authentik blueprint re-apply check

```bash
docker logs --since 5m infra-authentik-worker-1 \
  | grep -iE 'blueprint|apply|error' | tail -40
```

### 7.6 Cleanup

```bash
# Only after you are satisfied:
rm -rf ~/restore-temp/2026-04-20
```

---

## 8. Common failure modes

| Symptom | Likely cause | Fix |
|---|---|---|
| `No backups found at s3://backups/<date>/` | Typo in `restore_date`, or RustFS bucket empty | Re-list with `aws s3 ls backups/` |
| `infra-mariadb-1 is not running` | Infra stack down | `ansible-playbook main.yml -K --tags stacks` first |
| `docker exec` fails with `ERROR 1049 Unknown database` | Dump references DBs dropped at restore time | Safe to ignore for `DROP DATABASE` statements in the dump; verify with §7.2 |
| Authentik POST returns 401 | `authentik_bootstrap_token` unset in credentials | Add it to `credentials.yml` or re-run blueprint apply via `--tags authentik_oidc` |
| Volume restore stops containers but never restarts them | A container died while stopped | `docker start <name>` manually; inspect `docker logs <name>` |
| `gunzip: invalid compressed data` | Corrupt or partially-uploaded backup | Pick the previous date |
| Playbook skips everything unexpectedly | Forgot `-e restore_date=…` | Re-run with the CLI var |

If a restore half-succeeds (MariaDB good, Postgres fails), re-run with
`restore_sources=postgres` to retry just the failed source — the task is
idempotent per-source.

---

## 9. Related

- [`tasks/backup.yml`](../tasks/backup.yml) and `roles/pazny.backup/` — the
  producer side of this contract.
- [`files/anatomy/docs/coexistence-playbook.md`](../files/anatomy/docs/coexistence-playbook.md) — test-restore
  pattern.
- [`files/anatomy/docs/framework-overview.md`](../files/anatomy/docs/framework-overview.md) — migrations and
  upgrades, which sometimes pair with a restore.
