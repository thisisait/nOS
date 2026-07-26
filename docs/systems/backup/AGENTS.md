# Backup — Agent Definition

## BackupAgent

**System:** Backup (nightly launchd job, host-native)
**Domain:** none — no service, no UI, no port.
**Role:** Watches the nightly backup job and can trigger an off-cycle run or read its status. Restore is a destructive, operator-supervised playbook operation; an agent surfaces and prepares it but does not run it unattended.

### Context

- Runs as host launchd `eu.thisisait.nos.backup.rustfs` at 03:00 daily; script `~/.nos/backup.sh`.
- Freshness signal: `~/.nos/backup-status.json` (`last_run`); the manifest health probe fails if it is older than 36h.
- Uploads AES-256-encrypted logical dumps to the RustFS `backups` bucket (`http://127.0.0.1:9010`).

### Capabilities

- Read backup status/freshness from `~/.nos/backup-status.json`.
- Trigger an off-cycle backup via the launchd label.
- Report drift (last run too old, status file missing) — this is the signal the `05-backup` alerts watch.

### Non-capabilities

- No unattended restore. Restore replays live data over running services and is gated behind `--tags restore -e restore_date=…` with `never` tagging so it cannot fire by accident.
- No network API — everything is host-local shell + playbook tags.

### Skills Reference

See [SKILLS.md](SKILLS.md) for the callable actions.
