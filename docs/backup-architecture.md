# Backup & restore architecture

Authoritative design for how nOS backs up and restores. Decided 2026-06-09 from
a full audit (the two mechanisms, the data set, the restore path, cross-platform).
**Status: design — fix backlog below not yet implemented.**

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
| Target | local RustFS S3 `http://127.0.0.1:9010` bucket `backups` | external **USB/SSD** repo (operator-rotated off-site) — *decision 2026-06-09* |
| Form | logical dumps + volume tars + blueprint JSON, AES-256-CBC/pbkdf2 client-side | restic repo (restic-native encryption via `restic_password`) |
| Restore | `tasks/restore.yml` (full + partial, decrypt, replay into live containers) | restic restore → then the same replay |
| Schedule | launchd/systemd nightly **03:00** | **04:00** (staggered — replicates a *completed* RustFS run) |

**Why both:** RustFS is fast + granular but lives on the **same disk** as live
data (with `configure_external_storage=true`, `rustfs_data_dir` even redirects
to the SAME external SSD — `tasks/stacks/external-paths.yml`), so it is **not an
independent failure domain**. Restic on a rotated external disk is the
off-site/second-medium copy. Both consume the **same canonical data set**.

## Canonical data set (replaces the whole-`$HOME` default)

**Back up (irreplaceable):**
- **DB dumps** (logical, portable): MariaDB `mariadb-dump --all-databases`
  (wordpress, nextcloud, freescout, erpnext, bookstack, firefly, …);
  PostgreSQL `pg_dumpall` (authentik, infisical, outline, metabase, superset,
  paperclip). *Logical dumps are self-contained → the `*_data` DB volumes are
  redundant and dropped from the volume list.*
- **`wing.db`** (`{{ wing_data_dir }}/wing.db`) — security findings, remediation
  queue, **audit hash-chain**, agent sessions, GDPR/`actor_action_id` lineage.
  **ZERO coverage today.** Add `sqlite3 wing.db .dump | gzip | encrypt`.
- **`~/.nos/secrets.yml` + `~/.nos/state.yml`** — encryption keys, API/bootstrap
  tokens, break-glass codes, Infisical admin token; `upgrades_applied` history.
  **ZERO coverage today.** Tar+encrypt. (Exclude `backup-status.json`/`backup.log`.)
- **Authentik blueprints** (`/api/v3/managed/blueprints/`) — OIDC/flows/RBAC
  *definitions*. NOTE: live users/groups/sessions are in the Authentik **Postgres
  DB** (covered by `pg_dumpall`) — full Authentik state = blueprint JSON + the PG
  dump together.
- **Non-DB named volumes** — services on Docker named volumes (e.g. erpnext
  sites, authentik_media). *Operator confirms the live `docker volume ls` set
  (decision pending).* Today only `mariadb_data` is listed — the wrong one.
- **Service data dirs under `$HOME`** (host binds, incl. the data-loss holes):
  `gitea`, `gitlab` + `gitlab-config`, `nextcloud-data`, `n8n`, `outline/data`,
  `woodpecker`, `portainer`, `erpnext/sites`, `paperclip`, `authentik`,
  `infisical`, `vaultwarden`. **Gitea/GitLab repos are in NEITHER backup today.**
  Derive paths from the `*_data_dir` vars so `configure_external_storage`
  redirects (to `/Volumes/SSD1TB`) are honoured — never `$HOME`-relative literals.

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

> 🔴 **CRITICAL — restore is BROKEN today, not merely untested.** `backup.sh`
> writes object keys `mariadb-all.<ts>.sql.gz[.enc]` / `postgresql-all.<ts>…` /
> `authentik-blueprints.<ts>…`, but `tasks/restore.yml` filters the source stem
> as `mariadb`/`postgres` and gunzips hardcoded `mariadb.sql.gz`/`postgres.sql.gz`
> — the stem never matches, so **every DB dump is silently dropped from the
> restore plan**, and even forced through, the gunzip target file does not exist.
> The DB half of restore has never worked.

## Cross-platform

Same `~/.nos/backup.sh` on both OSes; scheduler differs (launchd
`StartCalendarInterval` gated `nos_service_manager=='launchd'`; systemd --user
oneshot+timer gated `'systemd-user'`). `restore.yml` is a one-shot play (OS-
agnostic). Two consistency fixes: (a) `restore.yml` calls bare `openssl enc -d`
but `backup.sh` resolves a `-pbkdf2`-capable binary — mirror `resolve_openssl()`
into restore (old LibreSSL fails); (b) `backup.sh` tars volumes with `alpine:3`
but `_restore_volume.yml` uses `alpine:3.20` — pin both identically.

## Fix backlog (implementation, post-doc-approval)

| # | Fix | Owner |
|---|-----|-------|
| 1 | **Restore object-naming contract** — normalize the stem (strip `.<ts>` + `-all`/`-blueprints`), drive gunzip off `item.file`, pin ONE canonical stem in backup.sh + restore.yml | assistant |
| 2 | **De-collide launchd labels** — `eu.thisisait.nos.backup.rustfs` vs `.offsite` (both currently `eu.thisisait.nos.backup` → enabling both silently disables one) | assistant |
| 3 | **`restic_backup_paths`** → the canonical list above (fixes macOS TCC rc=1; behaviour-preserving on Linux) | assistant |
| 4 | **Add `wing.db` + `~/.nos/{secrets,state}.yml`** to backup.sh + restore (with a `restore_state=true` gate so a restore never clobbers a NEWER live `secrets.yml` → SSO brick) | assistant |
| 5 | **Volume coverage** — drop `mariadb_data`, enumerate the genuinely-stateful non-DB volumes | operator confirms from live `docker volume ls` |
| 6 | **Off-site = external USB/SSD** — `restic_repo: /Volumes/<BackupDisk>/restic`, rotated off-site; `configure_backup:true` only when the disk is mounted | operator (set path + rotate) |
| 7 | **openssl + alpine-tag parity** (cross-platform) | assistant |
| 8 | **DR CI gate** — blank → playbook → backup → restore → `restore-verify` (assert DB list + row-count floor + volume mounts + Authentik user count + health), + a Linux leg | assistant (author) |

**Until the backlog lands:** set `configure_backup: false` (the whole-`$HOME`
Restic path aborts on macOS); the RustFS nightly (`install_backup:true`) keeps
running (copy #1), but **do not rely on restore** until fix #1 ships.
