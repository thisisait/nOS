#!/usr/bin/env bash
# =============================================================================
# nos-dgx backup VERIFIER — the reader that owns the verdict.
#
# Restores the latest snapshot's KEAP database into a scratch dir,
# counts the roadmap rows in it, asks the LIVE KEAP how many it holds, and
# writes both plus a verdict to /var/lib/nos-dgx/backup/last.json. Exit 0
# whatever it finds; an unreadable source is UNKNOWN, never OK. Runs daily at
# 04:30 (nos-dgx-backup-verify.timer) — a restore drill every day, on MBs.
#
#   verdict OK        latest snapshot < 26 h old, restore readable, rows ≥ 1
#   verdict STALE     snapshot older than 26 h (the backup did not run)
#   verdict BROKEN    restore failed or the restored db has no roadmap rows
#   verdict UNKNOWN   disk not mounted / repo unreadable / no snapshot yet
# =============================================================================
set -uo pipefail
export PATH=/usr/local/bin:/usr/bin:/bin
OUT=/var/lib/nos-dgx/backup/last.json
install -d -m 0711 "$(dirname "$OUT")"

emit() {  # emit <verdict> <detail> [snapshot_time] [snapshot_id] [rows_backup] [rows_live] [repo_size]
  python3 - "$@" <<'PY' > "$OUT.tmp" && mv "$OUT.tmp" "$OUT" && chmod 0644 "$OUT"
import json, sys, datetime
v = sys.argv[1:] + [""] * 7
print(json.dumps({
  "verified_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
  "verdict": v[0], "detail": v[1],
  "snapshot_time": v[2] or None, "snapshot_id": v[3] or None,
  "rows_backup": int(v[4]) if v[4] else None, "rows_live": int(v[5]) if v[5] else None,
  "repo_size": v[6] or None,
}, indent=1))
PY
  echo "$1: $2"
}

# shellcheck disable=SC1091
. /etc/nos/restic.env 2>/dev/null || { emit UNKNOWN "/etc/nos/restic.env unreadable"; exit 0; }
export RESTIC_REPOSITORY RESTIC_PASSWORD
# systemd gives no $HOME; restic needs a cache dir or refuses to open the repo.
export RESTIC_CACHE_DIR=/var/cache/nos-dgx-restic
install -d -m 0700 "$RESTIC_CACHE_DIR"
BK_MOUNT="${BK_MOUNT:-/srv/backup}"
mountpoint -q "$BK_MOUNT" || { emit UNKNOWN "$BK_MOUNT is not a mountpoint — backup disk absent"; exit 0; }

latest="$(restic snapshots --json --latest 1 2>/dev/null)" || { emit UNKNOWN "repository unreadable at $RESTIC_REPOSITORY"; exit 0; }
read -r sid stime < <(printf '%s' "$latest" | python3 -c 'import json,sys; s=json.load(sys.stdin); print((s[0]["short_id"]+" "+s[0]["time"]) if s else "")')
[ -n "${sid:-}" ] || { emit UNKNOWN "no nightly snapshot yet"; exit 0; }
age_h="$(python3 -c "import datetime,sys; t=datetime.datetime.fromisoformat(sys.argv[1].replace('Z','+00:00')); print(int((datetime.datetime.now(datetime.timezone.utc)-t).total_seconds()//3600))" "$stime")"
size="$(restic stats --json --mode raw-data latest 2>/dev/null | python3 -c 'import json,sys; d=json.load(sys.stdin); print(f"{d.get(\"total_size\",0)/2**30:.1f} GiB")' 2>/dev/null || echo "")"

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
if ! restic restore "$sid" --target "$tmp" --include /var/lib/nos-dgx/backup/stage/keap.db >/dev/null 2>&1; then
  emit BROKEN "restic restore of stage/keap.db from $sid failed" "$stime" "$sid" "" "" "$size"; exit 0
fi
db="$tmp/var/lib/nos-dgx/backup/stage/keap.db"
rows_backup="$(sqlite3 "$db" "select count(*) from table_rows where table_id='roadmap'" 2>/dev/null || echo "")"
[ -n "$rows_backup" ] || { emit BROKEN "restored keap.db unreadable or has no table_rows" "$stime" "$sid" "" "" "$size"; exit 0; }

rows_live=""
if [ -r /etc/nos/keap.env ]; then
  # shellcheck disable=SC1091
  . /etc/nos/keap.env
  rows_live="$(curl -s -m 10 -H "Authorization: Bearer ${KEAP_AGENT_TOKEN_RO:-}" \
    "${KEAP_API_URL:-http://127.0.0.1:8091}/agent/v1/tables/roadmap/rows" \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); d=d.get("data",d); print(len(d.get("rows",[]) if isinstance(d,dict) else d))' 2>/dev/null || echo "")"
fi

if [ "$age_h" -gt 26 ]; then
  emit STALE "latest nightly snapshot is ${age_h} h old" "$stime" "$sid" "$rows_backup" "$rows_live" "$size"
elif [ "$rows_backup" -lt 1 ]; then
  emit BROKEN "restored roadmap has 0 rows (live: ${rows_live:-?})" "$stime" "$sid" "$rows_backup" "$rows_live" "$size"
else
  emit OK "restored $rows_backup roadmap rows from $sid (${age_h} h old; live ${rows_live:-?})" "$stime" "$sid" "$rows_backup" "$rows_live" "$size"
fi
