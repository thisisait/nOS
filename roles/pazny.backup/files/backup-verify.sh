#!/bin/bash
# ============================================================================
# nOS backup RESTORE DRILL
# Rendered from roles/pazny.backup/files/backup-verify.sh by Ansible.
# DO NOT EDIT BY HAND — changes are overwritten on the next playbook run.
# ============================================================================
# A backup nobody has ever restored is a hypothesis, not a backup.
#
# docs/backup-architecture.md recorded the restic→RustFS DR round-trip as
# "never verified", and on 2026-07-30 that turned out to be load-bearing: the
# `keap-db` source had failed every night since at least 07-25 while
# `backup-status.json` said so and nothing read it. This script closes the loop
# from the other end — it takes what is ACTUALLY in the bucket, decrypts it,
# decompresses it, opens it, and asserts the contents are usable.
#
# It never touches live data: everything happens in a temp dir that is removed
# on exit, and nothing is written back to the bucket.
#
# Exit: 0 = every checked artifact restored and looked sane, 1 = at least one
# did not. Wired to A9 so a failure reaches ntfy rather than an unread inbox.
# ============================================================================
# shellcheck disable=SC2034,SC2155
set -u -o pipefail

export AWS_ACCESS_KEY_ID="{{ backup_target_access_key }}"
export AWS_SECRET_ACCESS_KEY="{{ backup_target_secret_key }}"
export AWS_DEFAULT_REGION="{{ backup_target_region | default('us-east-1') }}"

S3_ENDPOINT="{{ backup_target_endpoint }}"
S3_BUCKET="{{ backup_target_bucket }}"
AWS_OPTS=(--endpoint-url "${S3_ENDPOINT}")

ENCRYPT="{{ 'true' if backup_encryption_enabled else 'false' }}"
ENC_PASSPHRASE="{{ backup_encryption_passphrase | default('') }}"

LOG_FILE="{{ backup_verify_log | default(ansible_facts['env']['HOME'] + '/.nos/backup-verify.log') }}"
RESULT_FILE="{{ backup_verify_result | default(ansible_facts['env']['HOME'] + '/.nos/backup-verify.json') }}"

DO_NOTIFY="{{ 'true' if backup_notify_enabled | default(true) else 'false' }}"
NOTIFY_HMAC_SECRET="{{ bone_secret | default('') }}"
BONE_NOTIFY_URL="http://127.0.0.1:{{ bone_port | default(8099) }}/api/v1/notifications"

WORKDIR=""
# Results accumulate in a FILE, not a bash array: details contain spaces, and
# expanding an array inside the Python heredoc below would split on them. A
# file also keeps this template free of bash array-length syntax, whose
# dollar-brace-hash opening reads as a Jinja comment-open and breaks the render
# (memory: jinja-rendered-shell-brace-hash-trap — it bit backup.sh once already,
# and it bit this very comment on the first draft).
RESULT_TSV=""

log() {
    printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "${LOG_FILE}"
}

cleanup() {
    [[ -n "${WORKDIR}" && -d "${WORKDIR}" ]] && rm -rf "${WORKDIR}"
}
trap cleanup EXIT

record() {
    # name | ok(0/1) | detail  — one line per artifact, tab-separated
    printf '%s\t%s\t%s\n' "$1" "$2" "$3" >> "${RESULT_TSV}"
}

# Decrypt if the object carried the .enc suffix; passthrough otherwise.
decrypt_stream() {
    if [[ "${ENCRYPT}" == "true" ]]; then
        openssl enc -d -aes-256-cbc -md sha512 -pbkdf2 -iter 100000 \
            -salt -pass env:NOS_BACKUP_PASS
    else
        cat
    fi
}

latest_date() {
    aws "${AWS_OPTS[@]}" s3 ls "s3://${S3_BUCKET}/" 2>/dev/null \
      | awk '/PRE/ { gsub("/","",$2); print $2 }' \
      | grep -E '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' \
      | sort \
      | tail -1
}

fetch() {
    # $1 = stem (e.g. keap-db.gz) -> writes ${WORKDIR}/$1, returns 1 if absent
    local stem="$1" suffix=""
    [[ "${ENCRYPT}" == "true" ]] && suffix=".enc"
    aws "${AWS_OPTS[@]}" s3 cp "s3://${S3_BUCKET}/${DATE_STR}/${stem}${suffix}" - 2>/dev/null \
      | decrypt_stream > "${WORKDIR}/${stem}"
    [[ -s "${WORKDIR}/${stem}" ]]
}

# ── keap-db: a BINARY online .backup copy, not a SQL dump ────────────────────
# The vector index uses libsql_vector_idx(), so a host `.dump`/replay cannot
# reproduce it — which is exactly why the artifact is binary and why this check
# opens it rather than replaying it.
verify_keap_db() {
    log "keap-db: fetching ${DATE_STR}/keap-db.gz"
    if ! fetch "keap-db.gz"; then
        record "keap-db" 0 "no object at ${DATE_STR} (or it decrypted to nothing)"
        log "keap-db: MISSING"
        return 1
    fi
    if ! gunzip -c "${WORKDIR}/keap-db.gz" > "${WORKDIR}/keap.db" 2>>"${LOG_FILE}"; then
        record "keap-db" 0 "gunzip failed"
        log "keap-db: gunzip FAILED"
        return 1
    fi

    local rows
    # Row counts, not `pragma integrity_check` — the latter aborts on
    # libsql_vector_idx() under stock sqlite3 and would report a false failure.
    rows="$(sqlite3 "${WORKDIR}/keap.db" \
        "select (select count(*) from taxonomy_nodes_ext) || '/' ||
                (select count(*) from relations) || '/' ||
                (select count(*) from knowledge_objects);" 2>>"${LOG_FILE}")"
    if [[ -z "${rows}" ]]; then
        record "keap-db" 0 "restored file is not a readable SQLite database"
        log "keap-db: UNREADABLE"
        return 1
    fi
    case "${rows}" in
        0/*|*/0/*|*/0)
            record "keap-db" 0 "restored but a core table is EMPTY (nodes/relations/objects = ${rows})"
            log "keap-db: EMPTY CORE TABLE (${rows})"
            return 1
            ;;
    esac
    record "keap-db" 1 "nodes/relations/objects = ${rows}"
    log "keap-db: OK (${rows})"
}

# ── wing-db: a sqlite3 .dump (SQL text) — replay it into a scratch DB ────────
verify_wing_db() {
    log "wing-db: fetching ${DATE_STR}/wing-db.sql.gz"
    if ! fetch "wing-db.sql.gz"; then
        record "wing-db" 0 "no object at ${DATE_STR}"
        log "wing-db: MISSING"
        return 1
    fi
    if ! gunzip -c "${WORKDIR}/wing-db.sql.gz" > "${WORKDIR}/wing.sql" 2>>"${LOG_FILE}"; then
        record "wing-db" 0 "gunzip failed"
        log "wing-db: gunzip FAILED"
        return 1
    fi
    if ! sqlite3 "${WORKDIR}/wing-replay.db" < "${WORKDIR}/wing.sql" 2>>"${LOG_FILE}"; then
        record "wing-db" 0 "SQL replay failed — the dump is not restorable"
        log "wing-db: REPLAY FAILED"
        return 1
    fi
    local n
    n="$(sqlite3 "${WORKDIR}/wing-replay.db" "select count(*) from events;" 2>>"${LOG_FILE}")"
    if [[ -z "${n}" || "${n}" == "0" ]]; then
        record "wing-db" 0 "replayed but events table is empty"
        log "wing-db: EMPTY"
        return 1
    fi
    record "wing-db" 1 "replayed, events = ${n}"
    log "wing-db: OK (events=${n})"
}

write_result() {
    python3 - <<PY
import json, os, time
out = []
try:
    with open("${RESULT_TSV}") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            parts = line.split("\t", 2)
            if len(parts) < 2:
                continue
            out.append({
                "name": parts[0],
                "success": parts[1] == "1",
                "detail": parts[2] if len(parts) > 2 else "",
            })
except OSError:
    pass
with open(os.path.expanduser("${RESULT_FILE}"), "w") as f:
    json.dump({"checked_at": int(time.time()), "backup_date": "${DATE_STR}", "artifacts": out}, f, indent=2)
PY
}

notify() {
    [[ "${DO_NOTIFY}" != "true" ]] && return 0
    [[ -z "${NOTIFY_HMAC_SECRET}" ]] && { log "notify: HMAC secret empty — skipping"; return 0; }
    python3 - <<PY >> "${LOG_FILE}" 2>&1 || log "notify: POST failed (non-fatal)"
import hashlib, hmac, json, os, time, urllib.request
try:
    with open(os.path.expanduser("${RESULT_FILE}")) as f:
        s = json.load(f)
except Exception:
    s = {"artifacts": []}
arts = s.get("artifacts") or []
bad = [a["name"] for a in arts if not a.get("success")]
if bad:
    sev = "high"
    title = "Restore drill FAILED for: %s" % ", ".join(bad)
elif not arts:
    sev = "high"
    title = "Restore drill checked NOTHING (no artifacts found)"
else:
    sev = "info"
    title = "Restore drill OK - %d artifact(s) from %s" % (len(arts), s.get("backup_date", "?"))
body = "\n".join("%s: %s - %s" % (a["name"], "ok" if a.get("success") else "FAIL", a.get("detail", ""))
                 for a in arts) or "(nothing checked)"
payload = {
    "severity": sev,
    "title": title,
    "body": body,
    "actor_id": "backup-verify",
    "origin_plugin": "backup",
    "metadata": {"failed": bad, "backup_date": s.get("backup_date")},
}
raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
ts = str(int(time.time()))
sig = hmac.new("${NOTIFY_HMAC_SECRET}".encode("utf-8"),
               ts.encode("utf-8") + b"." + raw, hashlib.sha256).hexdigest()
req = urllib.request.Request(
    "${BONE_NOTIFY_URL}", data=raw, method="POST",
    headers={"Content-Type": "application/json",
             "X-Wing-Timestamp": ts,
             "X-Wing-Signature": sig})
with urllib.request.urlopen(req, timeout=10) as resp:
    print("notify: HTTP %s" % resp.status)
PY
}

main() {
    mkdir -p "$(dirname "${LOG_FILE}")"
    touch "${LOG_FILE}"
    log "==== nOS restore drill start ===="

    command -v sqlite3 >/dev/null 2>&1 || { log "FATAL: sqlite3 not on PATH"; exit 1; }
    command -v aws >/dev/null 2>&1 || { log "FATAL: aws not on PATH"; exit 1; }
    [[ "${ENCRYPT}" == "true" ]] && export NOS_BACKUP_PASS="${ENC_PASSPHRASE}"

    DATE_STR="${1:-$(latest_date)}"
    if [[ -z "${DATE_STR}" ]]; then
        log "FATAL: no dated prefixes in s3://${S3_BUCKET}/ — nothing has ever been backed up"
        exit 1
    fi
    log "verifying backup set ${DATE_STR}"

    WORKDIR="$(mktemp -d -t nos-verify-XXXXXX)"
    RESULT_TSV="${WORKDIR}/results.tsv"
    : > "${RESULT_TSV}"

    local rc=0
    verify_keap_db || rc=1
    verify_wing_db || rc=1

    write_result
    notify

    if [[ "${rc}" -ne 0 ]]; then
        log "==== nOS restore drill FAILED ===="
    else
        log "==== nOS restore drill OK ===="
    fi
    return "${rc}"
}

main "$@"
