#!/usr/bin/env bash
# =============================================================================
# nos-dgx nightly backup — restic to the local backup disk. Runs as root from
# nos-dgx-backup.timer (03:00). It writes NO success marker: the verifier
# (nos-dgx-backup-verify.sh) restores from the repository and says what it
# found — a backup that reports its own success is the defect nOS keeps
# finding (success markers must be written by a reader).
#
# What goes in, and why it is safe to copy:
#   /etc/nos                      tokens, CA, Hub config — the only copy
#   stage/*.db                    ONLINE sqlite snapshots (.backup) of KEAP,
#                                 Open WebUI, n8n, JupyterHub — WAL-safe, no stop
#   /srv/nos-dgx/keap/data        minus the live db files (the snapshot has them)
#   docker volumes open-webui, n8n minus their live db files
#   /srv/nos-seed.git             the shared roadmap seed repo
#   /home                         minus each user's docker store, caches, venvs
#   /etc/nginx/tls, user-slice drop-in, accounts (passwd/group/shadow/subuid)
#   stage/ollama-models.txt, docker-images.txt, dpkg-selections.txt — lists,
#                                 so a rebuild knows what to pull; never the blobs
#
# Retention (operator, 2026-09-07): 8 weekly; 7 daily kept as a cushion
# (dedup makes them nearly free). prune weekly (Sunday), check 10% weekly.
# =============================================================================
set -euo pipefail
export PATH=/usr/local/bin:/usr/bin:/bin

# shellcheck disable=SC1091
. /etc/nos/restic.env                    # RESTIC_REPOSITORY, RESTIC_PASSWORD
export RESTIC_REPOSITORY RESTIC_PASSWORD
# systemd gives no $HOME; restic needs a cache dir or refuses to open the repo.
export RESTIC_CACHE_DIR=/var/cache/nos-dgx-restic
install -d -m 0700 "$RESTIC_CACHE_DIR"
BK_MOUNT="${BK_MOUNT:-/srv/backup}"
RT=/srv/nos-dgx
STAGE=/var/lib/nos-dgx/backup/stage
LOG=/var/lib/nos-dgx/backup/backup.log

log() { printf '%s %s\n' "$(date -Is)" "$*" | tee -a "$LOG"; }

if ! mountpoint -q "$BK_MOUNT"; then
  log "REFUSING: $BK_MOUNT is not a mountpoint (backup disk absent) — nothing written"
  exit 75
fi
[ -d "$RESTIC_REPOSITORY" ] || { log "REFUSING: repository $RESTIC_REPOSITORY missing (run setup-root.sh)"; exit 75; }

install -d -m 0700 "$STAGE"
rm -rf "${STAGE:?}"/*
install -d -m 0700 "$STAGE/etc"

# ── online snapshots of every live SQLite database ───────────────────────────
snap() {  # snap <live.db> <name>
  [ -f "$1" ] || { log "skip $2: $1 absent"; return 0; }
  sqlite3 "$1" ".backup '$STAGE/$2.db'" && log "snapshot $2 ($(du -h "$STAGE/$2.db" | cut -f1))"
}
snap /srv/nos-dgx/keap/data/keap.db                          keap
snap /var/lib/docker/volumes/open-webui/_data/webui.db       webui
snap /var/lib/docker/volumes/iiab_n8n_data/_data/database.sqlite n8n
snap /var/lib/nos-dgx/jupyterhub/jupyterhub.sqlite           jupyterhub

# ── inventories: what to pull again, not the blobs ───────────────────────────
OLLAMA_HOST=http://172.17.0.1:11434 ollama list > "$STAGE/ollama-models.txt" 2>/dev/null || true
docker image ls --format '{{.Repository}}:{{.Tag}} {{.Size}}' > "$STAGE/docker-images.txt" 2>/dev/null || true
dpkg --get-selections > "$STAGE/dpkg-selections.txt"
for f in passwd group shadow gshadow subuid subgid fstab; do cp -p "/etc/$f" "$STAGE/etc/$f"; done
ls /var/lib/systemd/linger > "$STAGE/linger.txt" 2>/dev/null || true

# ── the backup ───────────────────────────────────────────────────────────────
log "restic backup → $RESTIC_REPOSITORY"
restic backup --tag nightly --one-file-system --exclude-caches \
  --exclude-file="$RT/backup/excludes.txt" \
  /etc/nos "$STAGE" /srv/nos-dgx/keap/data /srv/nos-seed.git \
  /var/lib/nos-dgx/jupyterhub /var/lib/docker/volumes/open-webui/_data \
  /var/lib/docker/volumes/iiab_n8n_data/_data \
  /home /etc/nginx/tls /etc/systemd/system/user-.slice.d \
  2>&1 | tail -n 6 | tee -a "$LOG" || rc=$?
# restic exit 3 = snapshot saved, some files unreadable (a vanished tmp file in
# a home dir) — worth a log line, not an abort; anything else is a failure.
case "${rc:-0}" in 0) ;; 3) log "warning: snapshot saved with unreadable files (rc=3)";; *) log "restic backup FAILED rc=$rc"; exit "$rc";; esac

# ── retention: forget nightly, prune + check on Sundays ─────────────────────
if [ "$(date +%u)" = 7 ]; then
  log "forget --prune (Sunday)"
  restic forget --tag nightly --keep-daily 7 --keep-weekly 8 --prune 2>&1 | tail -n 4 | tee -a "$LOG"
  log "check --read-data-subset=10%"
  restic check --read-data-subset=10% 2>&1 | tail -n 3 | tee -a "$LOG"
else
  restic forget --tag nightly --keep-daily 7 --keep-weekly 8 2>&1 | tail -n 2 | tee -a "$LOG"
fi
log "done (verdict is the verifier's, not this script's)"
