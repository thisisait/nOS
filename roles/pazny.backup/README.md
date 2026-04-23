# pazny.backup

Nightly backups of stateful nOS services → RustFS (S3-compatible) bucket.

## What it does

1. **Schedules** a LaunchAgent (`eu.thisisait.nos.backup`) that runs every day at
   03:00 local time (configurable via `backup_schedule_hour` / `_minute`).
2. **Renders** `~/.nos/backup.sh` — a self-contained shell script that performs:
   - `mariadb-dump --all-databases | gzip` → `s3://backups/<date>/mariadb-all.<ts>.sql.gz`
   - `pg_dumpall | gzip` → `s3://backups/<date>/postgresql-all.<ts>.sql.gz`
   - For each Docker named volume in `backup_volumes_to_dump`:
     `tar -czf - /data` (via disposable alpine container) → `s3://backups/<date>/volume-<name>.<ts>.tar.gz`
   - Authentik blueprint JSON (via REST API) → `s3://backups/<date>/authentik-blueprints.<ts>.json.gz`
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
       {"name": "volume:mariadb_data", "size_bytes": 2345678, "duration_ms": 7100, "success": true, "timestamp": 1746832812},
       {"name": "authentik",     "size_bytes":   3456, "duration_ms":  400, "success": true, "timestamp": 1746832814}
     ]
   }
   ```

   Agent C3's Glasswing dashboard reads this file.

## Idempotence

By default, the script **overwrites** same-day dumps (`backup_overwrite_same_day: true`).
Flip to `false` if you want the first success of the day to stick and subsequent
runs to no-op. Timestamps in filenames mean "overwrite" really means "add another";
rotation cleans duplicates out on its next pass.

## Ad-hoc triggers

Anything can also be run manually:

```bash
# Just run the nightly job right now
~/.nos/backup.sh

# Rotate only (delete expired prefixes, no new backups)
~/.nos/backup.sh --rotate-only
```

Or via Ansible — each `dump_*` task file can be `include_task`-ed from another
playbook if you want fine-grained control.

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
| `backup_volumes_to_dump` | `[mariadb_data]` | Docker named volumes to tar |
| `backup_run_now` | `false` | Execute `backup.sh` right after deploy (testing) |

## Dependencies

- RustFS stack up and reachable at `backup_target_endpoint`
- `awscli` (installed by this role via Homebrew)
- `docker` (for `docker exec` / `docker run`)
- MariaDB + PostgreSQL containers, if those backups are enabled
- Authentik with bootstrap token in `authentik_bootstrap_token` (optional)

## Logs

`~/.nos/backup.log` (also streamed by launchd's StandardOut/ErrorPath).
