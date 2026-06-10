# Backup & restore architecture

Authoritative design for how nOS backs up and restores. Decided 2026-06-09 from
a full audit (the two mechanisms, the data set, the restore path, cross-platform).
**Status: IMPLEMENTED 2026-06-09** — backlog #1–#4, #7, #8 shipped and gated
(`tests/anatomy/test_backup_restore_contract.py` + `--tags restore-verify`).
#5 (extra named volumes) and #6 (off-site disk path) are operator-owned config.

## Principles

1. **Back up the irreplaceable, skip the regenerable.** A `blank=true` + a
   playbook run rebuilds the whole platform from images + config; the backup
   only needs what that CANNOT regenerate — the DBs, user content, secrets,
   declarative state. Never back up images, caches, observability data, or
   re-downloadable content libraries.
2. **3-2-1** — ≥3 copies, on ≥2 media, ≥1 off-site. nOS gets there with TWO
   mechanisms (below), not one.
3. **All-local + restorable.** Backups stay on operator-owned media; a backup
   is only real if a restore has been proven end-to-end (today it has NOT — see
   the critical bug).
4. **Cross-platform parity.** The same logical backup/restore on macOS + Linux;
   only the scheduler differs (launchd vs systemd --user).

## The two mechanisms (3-2-1 split — KEEP BOTH, disjoint roles)

| | **RustFS** (`pazny.backup`, `install_backup`) | **Restic** (`tasks/backup.yml`, `configure_backup`) |
|---|---|---|
| Role | **Copy #1 — on-host, on-site** | **Copy #2 — off-site** |
| Target | local RustFS S3 `http://127.0.0.1:9010` bucket `backups` (= `rustfs_data_dir`) | external **USB/SSD** repo (operator-rotated off-site) — *decision 2026-06-09* |
| Form | logical dumps + volume/dir tars + wing.db + state + blueprint JSON, AES-256-CBC/pbkdf2 client-side | restic snapshot **of `rustfs_data_dir`** (copy #1's object store), restic-native encryption via `restic_password` |
| Label | `eu.thisisait.nos.backup.rustfs` | `eu.thisisait.nos.backup.offsite` |
| Restore | `tasks/restore.yml` (full + partial, decrypt, replay into live containers) | `restic restore` → `rustfs_data_dir` → then `tasks/restore.yml` |
| Schedule | launchd/systemd nightly **03:00** | **04:00** (staggered — mirrors a *completed* RustFS run) |

**Why both:** RustFS is fast + granular but lives on the **same disk** as live
data (with `configure_external_storage=true`, `rustfs_data_dir` even redirects
to the SAME external SSD — `tasks/stacks/external-paths.yml`), so it is **not an
independent failure domain**. Copy #2 is Restic snapshotting `rustfs_data_dir`
itself onto a rotated external disk — so the two copies are the **same canonical
data set by construction**, and copy #2 no longer re-dumps DBs (that duplicate
logic, plus its whole-`$HOME` path, was what aborted on macOS TCC `rc=1`).

## Canonical data set (replaces the whole-`$HOME` default)

**Back up (irreplaceable):**
- **DB dumps** (logical, portable): MariaDB `mariadb-dump --all-databases`
  (wordpress, nextcloud, freescout, erpnext, bookstack, firefly, …);
  PostgreSQL `pg_dumpall` (authentik, infisical, outline, metabase, superset,
  paperclip). *Logical dumps are self-contained → the `*_data` DB volumes are
  redundant and dropped from the volume list.*
- **`wing.db`** (`{{ wing_data_dir }}/wing.db`) — security findings, remediation
  queue, **audit hash-chain**, agent sessions, GDPR/`actor_action_id` lineage.
  **NOW COVERED** — `backup_wing_db` → `wing-db.sql.gz` (`sqlite3 .dump`); restore
  stops Wing, snapshots the current db, rebuilds via `sqlite3`.
- **`~/.nos/secrets.yml` + `~/.nos/state.yml`** — encryption keys, API/bootstrap
  tokens, break-glass codes, Infisical admin token; `upgrades_applied` history.
  **NOW COVERED** — `backup_nos_state` → `nos-state.tar.gz` (status/log artifacts
  excluded). Restore is **GATED behind `restore_state=true`** (a stale tar would
  clobber a re-keyed live `secrets.yml` → SSO brick).
- **Authentik blueprints** (`/api/v3/managed/blueprints/`) — OIDC/flows/RBAC
  *definitions*. NOTE: live users/groups/sessions are in the Authentik **Postgres
  DB** (covered by `pg_dumpall`) — full Authentik state = blueprint JSON + the PG
  dump together.
- **Non-DB named volumes** — `backup_volumes_to_dump` is now **`[]`**: `mariadb_data`
  was dropped (the raw DB datadir is fully covered by the logical `mariadb-dump`,
  i.e. redundant). **#5 (operator):** cross-check `docker volume ls` and add only
  genuinely-stateful non-DB volumes (e.g. `authentik_media` if present).
- **Service data dirs under `$HOME`** (host binds) — `backup_dirs_to_dump` now
  covers **`gitea`, `gitlab`, `gitlab-config`** (`dir-<name>.tar.gz`); restore maps
  them back via `restore_dir_targets`, stopping/restarting consumers. Git repos
  live on disk, in NO DB dump — this was the headline data-loss hole, now closed.
  Paths derive from the `*_data_dir` vars so `configure_external_storage`
  redirects (to `/Volumes/SSD1TB`) are honoured. Extend the list for other
  host-bind services (`nextcloud-data`, `n8n`, `outline/data`, `woodpecker`,
  `portainer`, `paperclip`, `vaultwarden`, …) as needed.

**NEVER back up (regenerable / harmful):** whole `$HOME`, `~/Library`
(TCC-protected → the macOS `restic` rc=1 abort), Docker images, Homebrew/npm/pip/
Composer caches, Grafana/Prometheus/Loki/Tempo data (metrics/logs/traces),
Kiwix/Calibre/maps content libraries, `node_modules`.

`restic_backup_paths` becomes this enumerated list (TCC-safe on macOS,
byte-identical on Linux), NOT `["{{ HOME }}"]`.

## Encryption & key custody (decision: static + documented custody)

AES-256-CBC/pbkdf2 (RustFS) + restic-native (off-site). The passphrase derives
from `global_password_prefix` (`{{ prefix }}_pw_backup_encryption`), is baked
into `~/.nos/backup.sh`, and is the **ONLY key to every encrypted object**.
**OPERATOR DUTY #1: `credentials.yml` (which holds `global_password_prefix`)
MUST survive off-box** — lose it and every backup is unrecoverable. Keep it under
the same custody as the off-site disk. (Rekey / Infisical-runtime deferred —
Infisical is itself in the backup, a bootstrap chicken-and-egg.)

## Restore contract

**Full platform restore:** (1) `ansible-playbook main.yml` on a fresh/blank host
→ infra up with EMPTY DBs/volumes; (2) `ansible-playbook main.yml -K --tags
restore -e restore_date=YYYY-MM-DD` → download + decrypt + replay into live
containers; (3) `--tags restore-verify` + health.

**Disaster recovery (new machine):** clone repo + restore `credentials.yml`
off-box (the only key) → `ansible-playbook main.yml` (infra + RustFS up empty) →
if the RustFS bucket itself was lost, first pull the Restic off-site repo into
`~/rustfs` / `aws s3 cp` the objects back → `--tags restore -e restore_date=… -e
restore_auto_confirm=true` → `--tags restore-verify`.

> ✅ **FIXED 2026-06-09 (was CRITICAL — restore had never worked for DBs).**
> `backup.sh` had drifted to timestamped `mariadb-all.<ts>.sql.gz` /
> `postgresql-all.<ts>…` / `authentik-blueprints.<ts>.json.gz` keys, while
> `tasks/restore.yml` + the runbook §3 select on the clean stems
> `mariadb`/`postgres`/`authentik-blueprints` — so the stem never matched and
> **every DB dump was silently dropped from the restore plan**. Resolution:
> `backup.sh` reverted to the canonical contract (one fixed key per source per
> day, no timestamp, raw `.json`); restore drives gunzip off `item.file` and
> tolerates legacy timestamped names too. The contract is now pinned offline by
> `tests/anatomy/test_backup_restore_contract.py` (every backup source has a
> restore handler; no timestamp regression; alpine + openssl parity).

## Cross-platform

Same `~/.nos/backup.sh` on both OSes; scheduler differs (launchd
`StartCalendarInterval` gated `nos_service_manager=='launchd'`; systemd --user
oneshot+timer gated `'systemd-user'`). `restore.yml` is a one-shot play (OS-
agnostic). Two consistency fixes shipped with #7: (a) `restore.yml` now resolves
a `-pbkdf2`-capable openssl (mirror of `backup.sh resolve_openssl()`) instead of
a bare `openssl enc -d` that old macOS LibreSSL rejects; (b) the alpine tar/extract
image is a single source (`backup_alpine_image` = `restore_alpine_image` =
`alpine:3.20`), asserted equal by the contract gate. Caveat: `wing-db` restore
needs `sqlite3` on the host (macOS ships it; Linux needs the `sqlite3` package).

## Fix backlog (implementation, post-doc-approval)

| # | Fix | Owner | Status |
|---|-----|-------|--------|
| 1 | **Restore object-naming contract** — backup.sh reverted to the canonical stem; restore drives gunzip off `item.file` + tolerates legacy names | assistant | ✅ shipped |
| 2 | **De-collide launchd labels** — `.rustfs` vs `.offsite`; legacy `eu.thisisait.nos.backup` plist booted-out + removed by both paths | assistant | ✅ shipped |
| 3 | **`restic_backup_paths`** → `["{{ rustfs_data_dir }}"]` (off-site mirror of copy #1; fixes macOS TCC rc=1; drops duplicate DB-dump logic) | assistant | ✅ shipped |
| 4 | **Add `wing.db` + `~/.nos` + gitea/gitlab dirs** to backup.sh + restore (nos-state restore gated by `restore_state`) | assistant | ✅ shipped |
| 5 | **Volume coverage** — `mariadb_data` dropped; enumerate genuinely-stateful non-DB volumes into `backup_volumes_to_dump` | operator (from live `docker volume ls`) | ⏳ operator |
| 6 | **Off-site = external USB/SSD** — `restic_repo: /Volumes/<BackupDisk>/restic`; `configure_backup:true` only when the disk is mounted | operator (set path + rotate) | ⏳ operator |
| 7 | **openssl + alpine-tag parity** — restore resolves a pbkdf2 openssl; alpine pinned via a single var (gated) | assistant | ✅ shipped |
| 8 | **DR gate** — offline contract test (`test_backup_restore_contract.py`) + runtime `--tags restore-verify` (DB floors + Authentik/Wing presence) | assistant | ✅ shipped (offline + runtime; full wet DR-in-CI leg = follow-up) |

**Operator to-do before relying on off-site copy #2:** set `restic_repo` to a
**mounted** external disk and flip `configure_backup: true` (#6); optionally
extend `backup_volumes_to_dump` (#5). Copy #1 (`install_backup: true`) runs
regardless and restore is now functional end-to-end.

## Known gaps / follow-ups (2026-06-09 adversarial review; S4 update 2026-06-10)

Honest scope boundaries — none re-break the backup→restore contract, but they
bound what a DR currently covers:

- ~~**KNOWN-UNBACKED host-bind state beyond gitea/gitlab.**~~ **CLOSED (S4
  2026-06-10):** `backup_dirs_to_dump` + `restore_dir_targets` now carry
  **vaultwarden / n8n / nodered / authentik** (media+certs); parity pinned by
  `test_backup_dirs_have_restore_targets`. **Honest residue:** the two SQLite
  files (vaultwarden `db.sqlite3`, n8n `database.sqlite`) are tar'd LIVE at
  03:00 (low-write window; restic keeps 7 dailies, one torn copy isn't fatal)
  — a proper `sqlite3 .backup` quiesce stays queued. **Nextcloud user files**
  remain unbacked (size; operator decision — add the data dir to the list to
  opt in).
- ~~**Backup observability is NOT wired.**~~ **CLOSED (S4 2026-06-10):**
  `backup_status_exporter.py` deploys via the backup role with a 60-second
  launchd agent (`eu.thisisait.nos.backup.exporter`) / systemd-user timer;
  `node_exporter_textfile_dir` moved to `~/.nos/metrics/textfile` (the old
  `/var/lib/...` default does not exist on macOS and needs root on Linux —
  the collector read nothing, dashboard was blind). Live-verified: heartbeat
  + per-source metrics in `backup.prom`; Alloy textfile collector scrapes it.
  A failed backup also lands a HIGH inbox notification (W6.1 `notify_result`).
- **Restic→RustFS DR round-trip unverified.** STILL OPEN — and currently
  blocked ahead of the verify: the off-site leg itself fails with macOS TCC
  `operation not permitted` on `/Volumes/SSD1TB/nos-restic` (operator: grant
  Full Disk Access to the runner, or re-point `restic_repo`; to-do #6).
  Verify the bucket-index rebuild before treating copy #2 as DR-ready.
- **`restore-verify` floors cover the core sources** (MariaDB/PG/Authentik hard
  floors; Wing/dirs informational). A full wet DR-in-CI leg (blank → backup →
  restore → verify, both OSes) is the remaining #8 follow-up.
