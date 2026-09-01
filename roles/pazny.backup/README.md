# pazny.backup

Copy #1 (on-host) of the 3-2-1 design: nightly encrypted backups of stateful nOS
services → RustFS (S3-compatible) bucket. The off-site copy #2 is `tasks/backup.yml`
(Restic, mirrors this bucket). See `docs/backup-architecture.md`.

## What it does

1. **Schedules** a LaunchAgent (`eu.thisisait.nos.backup.rustfs`) that runs every
   day at 03:00 local time (configurable via `backup_schedule_hour` / `_minute`).
   Renamed from `eu.thisisait.nos.backup` — it collided with the Restic off-site
   agent (now `.offsite`); the role boots out + removes the legacy plist.
2. **Renders** `~/.nos/backup.sh` — a self-contained shell script that writes ONE
   fixed object per source per day (NO timestamp, so restore can match the stem
   and `backup_overwrite_same_day` genuinely overwrites). Each is AES-256
   encrypted before upload (`.enc` suffix). The object stem IS the restore
   `source` (contract pinned by `tests/anatomy/test_backup_restore_contract.py`):
   - `mariadb-dump --all-databases | gzip` → `s3://backups/<date>/mariadb.sql.gz`
   - `pg_dumpall | gzip` → `s3://backups/<date>/postgres.sql.gz`
   - each Docker named volume in `backup_volumes_to_dump`:
     `tar -czf -` (disposable alpine) → `s3://backups/<date>/volume-<name>.tar.gz`
   - each host-bind dir in `backup_dirs_to_dump` (gitea/gitlab repos — state no DB
     dump can rebuild): `tar -czf -` → `s3://backups/<date>/dir-<name>.tar.gz`
   - Wing SQLite store (`sqlite3 .dump | gzip`) → `s3://backups/<date>/wing-db.sql.gz`
   - `~/.nos/{secrets,state}.yml` (`tar -czf -`) → `s3://backups/<date>/nos-state.tar.gz`
   - Authentik blueprint JSON (via REST API, raw) → `s3://backups/<date>/authentik-blueprints.json`
3. **Rotates** — classifies dated prefixes and keeps the last
   `backup_retention_daily` days / `_weekly` Sundays / `_monthly` month-firsts.
4. **Reports** — writes `~/.nos/backup-status.json` after every run:

   ```json
   {
     "last_run": 1746832800,
     "in_progress": false,
     "sources": [
       {"name": "mariadb",       "size_bytes": 123456, "duration_ms": 2100, "success": true, "timestamp": 1746832801},
       {"name": "postgresql",    "size_bytes":  98765, "duration_ms": 1500, "success": true, "timestamp": 1746832803},
       {"name": "dir:gitea",     "size_bytes": 9876543,"duration_ms": 8200, "success": true, "timestamp": 1746832812},
       {"name": "wing-db",       "size_bytes":  45678, "duration_ms":  600, "success": true, "timestamp": 1746832818},
       {"name": "nos-state",     "size_bytes":   2048, "duration_ms":  120, "success": true, "timestamp": 1746832819},
       {"name": "authentik",     "size_bytes":   3456, "duration_ms":  400, "success": true, "timestamp": 1746832820}
     ]
   }
   ```

   Agent C3's Wing dashboard reads this file.

## Idempotence

By default, the script **overwrites** same-day objects (`backup_overwrite_same_day: true`)
— each source is ONE fixed key per day, so a re-run genuinely overwrites it.
Flip to `false` if you want the first success of the day to stick and subsequent
runs to no-op. (Object keys carry no timestamp — that was a bug: it turned
"overwrite" into "add another" AND broke restore, whose source selector cannot
match a timestamped stem.)

## Ad-hoc triggers

```bash
# Run the nightly job right now
~/.nos/backup.sh        # (or: ansible-playbook main.yml --tags backup -e backup_run_now=true)

# Rotate only (delete expired prefixes, no new backups)
~/.nos/backup.sh --rotate-only
```

(The old standalone `dump_*.yml` task files were removed — they were unwired,
shipped cleartext, and emitted a competing drifted contract. `backup_run_now`
covers the on-demand case.)

## Configuration

See `defaults/main.yml`. Key tunables:

| Var | Default | Purpose |
|-----|---------|---------|
| `backup_schedule_hour` / `_minute` | `3` / `0` | Local-time wake-up |
| `backup_target_bucket` | `backups` | Bucket name on RustFS |
| `backup_target_endpoint` | `http://127.0.0.1:9010` | RustFS S3 API |
| `backup_retention_daily` | `7` | Daily snapshots kept |
| `backup_retention_weekly` | `4` | Weekly (Sunday) snapshots |
| `backup_retention_monthly` | `12` | Monthly (day-1) snapshots |
| `backup_volumes_to_dump` | `[]` | Docker NAMED volumes to tar (DB `*_data` dropped — redundant vs the logical dump; add genuinely-stateful non-DB volumes) |
| `backup_dirs_to_dump` | gitea/gitlab/gitlab-config | Host-bind dirs to tar (git repos — covered by no DB dump) |
| `backup_wing_db` / `backup_wing_db_path` | `install_wing` / `…/wing.db` | sqlite3 .dump of the Wing store |
| `backup_nos_state` | `true` | tar `~/.nos/{secrets,state}.yml` (restore gated by `restore_state`) |
| `backup_alpine_image` | `alpine:3.20` | tar image; declared in `default.config.yml` only — restore derives it |
| `backup_run_now` | `false` | Execute `backup.sh` right after deploy (testing) |

## Dependencies

- RustFS stack up and reachable at `backup_target_endpoint`
- `awscli` (installed by this role via Homebrew)
- `docker` (for `docker exec` / `docker run`)
- MariaDB + PostgreSQL containers, if those backups are enabled
- Authentik with bootstrap token in `authentik_bootstrap_token` (optional)

## Logs

`~/.nos/backup.log` (also streamed by launchd's StandardOut/ErrorPath).
