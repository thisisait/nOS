#!/usr/bin/env bash
# =============================================================================
# nos-dgx backup STAGING — what must exist before restic reads the tree.
# Online SQLite snapshots (.backup, WAL-safe, no stop) of KEAP, Open WebUI,
# n8n and the Hub, plus the inventories a rebuild needs (model tags, images,
# packages, accounts). Called by Backrest's CONDITION_SNAPSHOT_START hook for
# plan `nightly`, and by nos-dgx-backup.sh for a manual run. Root.
# =============================================================================
set -euo pipefail
export PATH=/usr/local/bin:/usr/bin:/bin
STAGE=/var/lib/nos-dgx/backup/stage
LOG=/var/lib/nos-dgx/backup/backup.log
log() { printf '%s %s\n' "$(date -Is)" "$*" | tee -a "$LOG"; }

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

log "staging complete"
