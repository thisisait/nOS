#!/usr/bin/env bash
# deploy-from-ci.sh — host-side deploy wrapper invoked by Wing's
# DeployTriggerPresenter (A17, 2026-05-20).
#
# Spawned via PHP proc_open after HMAC validation. Receives:
#   $1 — deploy UUID (used for log path + correlation)
#   $2 — comma-separated tag list (already allowlist-validated by Wing)
#
# Runs `ansible-playbook main.yml --tags <tags>` against the operator's
# repo checkout (locked path: $HOME/projects/nOS — operator may override
# via NOS_REPO_DIR env). Streams stdout/stderr to
# $HOME/.nos/deploys/<uuid>.log, fires a Wing /api/v1/notifications POST
# on completion with rc + log-path.
#
# Concurrency: file lock at $HOME/.nos/deploys/.lock — if another deploy
# is in progress, this invocation logs the conflict and exits 0
# (the trigger endpoint returned 202 already; the user-visible
# notification reports "skipped due to lock").
#
# Security boundary: this script does NOT escalate privileges. Tags that
# touch sudo (homebrew, mac.*, autostart) are rejected by Wing BEFORE we
# get here. If a stray sudo task lands in the picked tags, ansible-playbook
# fails with "sudo: a password is required" — by design.

set -eu

DEPLOY_UUID="${1:-unknown}"
TAGS="${2:-}"
REPO_DIR="${NOS_REPO_DIR:-$HOME/projects/nOS}"
LOG_DIR="$HOME/.nos/deploys"
LOG_FILE="$LOG_DIR/${DEPLOY_UUID}.log"
LOCK_FILE="$LOG_DIR/.lock"

mkdir -p "$LOG_DIR"

# Concurrency guard — `flock -n` exits 1 immediately if locked.
exec 9>"$LOCK_FILE"
if ! flock -n 9 2>/dev/null; then
	# macOS coreutils lacks flock by default; fall back to mkdir-based lock
	# which is atomic enough for our 1-deploy-at-a-time guarantee.
	LOCK_DIR="$LOG_DIR/.lock.d"
	if ! mkdir "$LOCK_DIR" 2>/dev/null; then
		{
			echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] deploy ${DEPLOY_UUID} skipped: another deploy is in progress"
		} >> "$LOG_FILE"
		# Best-effort notification — non-fatal if it fails.
		_notify "warning" "Deploy skipped: lock held" "Another deploy was already in progress when ${DEPLOY_UUID} was triggered." || true
		exit 0
	fi
	# shellcheck disable=SC2064
	trap "rmdir '$LOCK_DIR' 2>/dev/null || true" EXIT
fi

# ── Notification helper ──────────────────────────────────────────────────
# Posts to Bone /api/v1/notifications via HMAC. WING_EVENTS_HMAC_SECRET
# is exported by the wing.plist env block; Bone re-uses the same secret
# for its /api/v1/notifications inserts. If the secret is missing, the
# notification step skips silently.
_notify() {
	local sev="${1:-info}"
	local title="${2:-deploy}"
	local body="${3:-}"
	local secret
	secret="${WING_EVENTS_HMAC_SECRET:-}"
	if [ -z "$secret" ]; then
		return 0
	fi
	local bone_url
	bone_url="${BONE_URL:-http://127.0.0.1:8099}"
	local payload
	payload=$(printf '{"severity":"%s","title":"%s","body":"%s","channels":["wing-inbox"],"origin_plugin":"ci-deploy","actor_id":"agent:ci-deploy"}' \
		"$sev" \
		"$(printf '%s' "$title" | sed 's/"/\\"/g')" \
		"$(printf '%s' "$body" | sed 's/"/\\"/g' | tr '\n' ' ')")
	local ts
	ts=$(date +%s)
	local sig
	sig=$(printf '%s.%s' "$ts" "$payload" \
		| openssl dgst -sha256 -hmac "$secret" \
		| awk '{print $NF}')
	curl -sf -o /dev/null --max-time 5 \
		-X POST -H "Content-Type: application/json" \
		-H "X-Wing-Timestamp: $ts" \
		-H "X-Wing-Signature: $sig" \
		--data "$payload" \
		"$bone_url/api/v1/notifications" || true
}

# ── Run the playbook ─────────────────────────────────────────────────────
START_EPOCH=$(date +%s)
{
	echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] deploy ${DEPLOY_UUID} starting"
	echo "  repo_dir : $REPO_DIR"
	echo "  tags     : $TAGS"
	echo "  pid      : $$"
	echo
} > "$LOG_FILE"

cd "$REPO_DIR"
ansible-playbook main.yml \
	--tags "$TAGS" \
	-e "nos_deploy_uuid=$DEPLOY_UUID" \
	-e "nos_deploy_source=ci" \
	>> "$LOG_FILE" 2>&1
RC=$?

END_EPOCH=$(date +%s)
DURATION=$((END_EPOCH - START_EPOCH))

{
	echo
	echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] deploy ${DEPLOY_UUID} finished"
	echo "  rc       : $RC"
	echo "  duration : ${DURATION}s"
} >> "$LOG_FILE"

if [ "$RC" -eq 0 ]; then
	_notify "info" "Deploy green: ${TAGS}" "deploy ${DEPLOY_UUID} succeeded in ${DURATION}s. Log: ${LOG_FILE}"
else
	_notify "high" "Deploy FAILED (rc=${RC}): ${TAGS}" "deploy ${DEPLOY_UUID} failed after ${DURATION}s. Log: ${LOG_FILE}"
fi

exit $RC
