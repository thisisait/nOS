# Backup — Skills

> Callable actions for the nightly backup job. These are host shell commands and playbook tags — there is no service API, because backup is a scheduled script, not a daemon.

## Authentication

- **Method:** N/A — no service, no port. Actions run as the operator on the host (or via the playbook).

---

## check-backup-status

**Trigger:** "is the backup fresh", "when did the last backup run", "check backup status"
**Method:** host file read
**Command:**
```bash
cat ~/.nos/backup-status.json
```
**Output:** JSON with `last_run` (epoch) and per-source results. The manifest health probe fails if `last_run` is older than 36h.

---

## run-backup-now

**Trigger:** "run a backup now", "trigger an off-cycle backup", "kick the backup job"
**Method:** launchd
**Command:**
```bash
launchctl kickstart -k "gui/$(id -u)/eu.thisisait.nos.backup.rustfs"
```
**Output:** the job runs immediately; progress lands in `~/.nos/backup.log`, results in `~/.nos/backup-status.json`.

---

## restore-from-backup

**Trigger:** "restore from a dated backup", "roll back to [date]", "replay a backup"
**Method:** playbook (destructive — operator-supervised, never unattended)
**Command:**
```bash
ansible-playbook main.yml -K --tags restore -e restore_date=YYYY-MM-DD
```
**Output:** pulls the dated objects from RustFS, decrypts, and replays them over the live services. Tagged `never` so a stray `restore_date` in config cannot trigger it. See `docs/restore-runbook.md`.

---

## verify-restore

**Trigger:** "verify the restore", "prove the backup restored", "check row counts after restore"
**Method:** playbook
**Command:**
```bash
ansible-playbook main.yml --tags restore-verify
```
**Output:** DB list + row-count floors + Authentik/Wing presence checks.
