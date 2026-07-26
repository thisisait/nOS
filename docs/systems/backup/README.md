# Backup

> The nightly backup job — a **host launchd agent** (not a container, no UI, no network surface). It takes app-consistent logical dumps of stateful services and uploads them, client-side-encrypted, to RustFS (on-host copy #1).

## Quick Reference

| | |
|---|---|
| **Runtime** | host launchd agent `eu.thisisait.nos.backup.rustfs` (not Docker) |
| **Schedule** | daily at `03:00` (`backup_schedule_hour`/`minute`, StartCalendarInterval) |
| **Toggle** | `install_backup: true` (default on) |
| **Script** | `~/.nos/backup.sh` (`backup_script_path`) |
| **Status** | `~/.nos/backup-status.json` (`backup_status_file`) |
| **Log** | `~/.nos/backup.log` (`backup_log_file`) |
| **Target** | RustFS S3 bucket `backups` at `http://127.0.0.1:9010` (`backup_target_*`) |
| **Retention** | `7` daily / `4` weekly / `12` monthly |
| **Manifest node** | `nos.host.backup` (no domain, no port) |

## Authentication

- **App-level auth:** N/A — there is no service, no UI, no listening port. It is a scheduled shell script running as the operator.
- **SSO bucket:** none.
- **S3 target:** signs RustFS requests with `rustfs_access_key` / `rustfs_secret_key`.
- **Client-side encryption:** every dump is AES-256-CBC/pbkdf2 encrypted before upload (`backup_encryption_enabled: true`); passphrase `{global_password_prefix}_pw_backup_encryption`. Encrypted objects carry a `.enc` suffix.

## What it backs up

- MariaDB logical dump (`backup_databases_mariadb`) and PostgreSQL logical dump (`backup_databases_postgresql`).
- Authentik blueprints (`backup_authentik_blueprints`, via the Authentik API on `authentik_port`).
- Wing SQLite store `wing.db` and, when enabled, KEAP `keap.db`.
- Runtime state side-car `~/.nos/{secrets,state}.yml` → `nos-state.tar.gz`.
- OpenTofu Authentik state (`terraform.tfstate` + rendered tfvars) → `tofu-state.tar.gz`.
- Host-bind dirs no DB dump can reconstruct: `gitea`, `gitlab`, `gitlab-config` (git repos on disk).

## Health Check

- **Type:** `exec` (manifest). Passes only if `~/.nos/backup-status.json` exists **and** its `last_run` is younger than 36h — a stale or missing status file fails the probe.

## Metrics

- `backup_status_exporter.py` (`eu.thisisait.nos.backup.exporter`, every 60s) turns `backup-status.json` into a textfile `.prom` for Alloy → the `91-backups` Grafana dashboard + `05-backup` alerts.

## Restore

- Restore is a separate, operator-run, destructive playbook path (never auto-triggered): `ansible-playbook main.yml -K --tags restore -e restore_date=YYYY-MM-DD`. See `docs/restore-runbook.md`.
- Post-restore proof: `ansible-playbook main.yml --tags restore-verify`.

## Dependencies

- RustFS (the S3 target — on-host copy #1 destination).
- aws-cli (RustFS S3 client, installed by the role).
- MariaDB / PostgreSQL / Authentik / Wing (the dump sources, when installed).
