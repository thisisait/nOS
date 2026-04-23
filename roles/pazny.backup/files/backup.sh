#!/bin/bash
# ============================================================================
# nOS nightly backup entrypoint
# Rendered from roles/pazny.backup/files/backup.sh by Ansible.
# DO NOT EDIT BY HAND — changes are overwritten on the next playbook run.
# ============================================================================
# shellcheck disable=SC2034,SC2155
set -u -o pipefail

# ---- Configuration (baked in by Ansible template) --------------------------
export AWS_ACCESS_KEY_ID="{{ backup_target_access_key }}"
export AWS_SECRET_ACCESS_KEY="{{ backup_target_secret_key }}"
export AWS_DEFAULT_REGION="{{ backup_target_region }}"

S3_ENDPOINT="{{ backup_target_endpoint }}"
S3_BUCKET="{{ backup_target_bucket }}"

MARIADB_CONTAINER="{{ backup_mariadb_container }}"
MARIADB_USER="{{ backup_mariadb_user }}"
MARIADB_PASSWORD="{{ backup_mariadb_password }}"
DO_MARIADB="{{ 'true' if backup_databases_mariadb else 'false' }}"

PG_CONTAINER="{{ backup_postgresql_container }}"
PG_USER="{{ backup_postgresql_user }}"
PG_PASSWORD="{{ backup_postgresql_password }}"
DO_POSTGRES="{{ 'true' if backup_databases_postgresql else 'false' }}"

AUTHENTIK_URL="{{ backup_authentik_url }}"
AUTHENTIK_TOKEN="{{ backup_authentik_token }}"
DO_AUTHENTIK="{{ 'true' if backup_authentik_blueprints else 'false' }}"

VOLUMES=({% for v in backup_volumes_to_dump %}"{{ v }}" {% endfor %})

RETAIN_DAILY={{ backup_retention_daily }}
RETAIN_WEEKLY={{ backup_retention_weekly }}
RETAIN_MONTHLY={{ backup_retention_monthly }}

STATUS_FILE="{{ backup_status_file }}"
LOG_FILE="{{ backup_log_file }}"
OVERWRITE_SAME_DAY="{{ 'true' if backup_overwrite_same_day else 'false' }}"

AWS_OPTS=(--endpoint-url "${S3_ENDPOINT}" --region "${AWS_DEFAULT_REGION}")

# ---- Helpers ---------------------------------------------------------------
log() {
    local ts
    ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "[${ts}] $*" | tee -a "${LOG_FILE}"
}

die() {
    log "FATAL: $*"
    exit 1
}

now_ms() {
    # GNU-date-free millisecond clock (macOS)
    python3 -c 'import time; print(int(time.time() * 1000))'
}

# Append a source entry to the status JSON. Args: name size_bytes duration_ms success(0/1)
status_append() {
    local name="$1" size="$2" duration="$3" success="$4"
    python3 - <<PY
import json, os, time
path = os.path.expanduser("${STATUS_FILE}")
try:
    with open(path) as f:
        s = json.load(f)
except Exception:
    s = {"last_run": 0, "sources": []}
if not isinstance(s.get("sources"), list):
    s["sources"] = []
s["sources"].append({
    "name": "${name}",
    "size_bytes": int("${size}" or 0),
    "duration_ms": int("${duration}" or 0),
    "success": bool(int("${success}" or 0)),
    "timestamp": int(time.time()),
})
with open(path, "w") as f:
    json.dump(s, f, indent=2)
PY
}

status_reset() {
    python3 - <<PY
import json, os
path = os.path.expanduser("${STATUS_FILE}")
with open(path, "w") as f:
    json.dump({"last_run": 0, "sources": [], "in_progress": True}, f)
PY
}

status_finalize() {
    python3 - <<PY
import json, os, time
path = os.path.expanduser("${STATUS_FILE}")
try:
    with open(path) as f:
        s = json.load(f)
except Exception:
    s = {"sources": []}
s["last_run"] = int(time.time())
s["in_progress"] = False
with open(path, "w") as f:
    json.dump(s, f, indent=2)
PY
}

# Get object size from S3 (0 if missing).
s3_size() {
    local key="$1"
    aws "${AWS_OPTS[@]}" s3api head-object \
        --bucket "${S3_BUCKET}" \
        --key "${key}" \
        --query ContentLength \
        --output text 2>/dev/null || echo 0
}

# Ensure bucket exists (RustFS: create-bucket is idempotent enough; ignore conflict).
ensure_bucket() {
    aws "${AWS_OPTS[@]}" s3api head-bucket --bucket "${S3_BUCKET}" 2>/dev/null && return 0
    log "Creating bucket s3://${S3_BUCKET}"
    aws "${AWS_OPTS[@]}" s3api create-bucket --bucket "${S3_BUCKET}" \
        >/dev/null 2>&1 || log "create-bucket returned non-zero (already exists?) — continuing"
}

# Skip a source if OVERWRITE_SAME_DAY=false and today already has the prefix.
already_exists_today() {
    local prefix="$1"
    local count
    count=$(aws "${AWS_OPTS[@]}" s3 ls "s3://${S3_BUCKET}/${prefix}" 2>/dev/null | wc -l | tr -d ' ')
    [[ "${count}" -gt 0 ]]
}

# ---- Source steps ----------------------------------------------------------
run_mariadb() {
    [[ "${DO_MARIADB}" != "true" ]] && return 0
    local date_str ts key start dur rc size
    date_str="$(date -u +%Y-%m-%d)"
    ts="$(date -u +%Y-%m-%dT%H-%M-%SZ)"
    key="${date_str}/mariadb-all.${ts}.sql.gz"

    if [[ "${OVERWRITE_SAME_DAY}" != "true" ]] && already_exists_today "${date_str}/mariadb-all."; then
        log "mariadb: today's dump already exists, skipping"
        status_append "mariadb" 0 0 1
        return 0
    fi

    log "mariadb: dumping via docker exec ${MARIADB_CONTAINER}"
    start=$(now_ms)
    docker exec -i "${MARIADB_CONTAINER}" \
        mariadb-dump \
          --all-databases \
          --single-transaction \
          --quick \
          --routines \
          --triggers \
          "-u${MARIADB_USER}" \
          "-p${MARIADB_PASSWORD}" \
      | gzip -c \
      | aws "${AWS_OPTS[@]}" s3 cp - "s3://${S3_BUCKET}/${key}"
    rc=$?
    dur=$(( $(now_ms) - start ))

    if [[ "${rc}" -eq 0 ]]; then
        size=$(s3_size "${key}")
        log "mariadb: OK (${size} bytes in ${dur}ms) → s3://${S3_BUCKET}/${key}"
        status_append "mariadb" "${size}" "${dur}" 1
    else
        log "mariadb: FAILED (rc=${rc})"
        status_append "mariadb" 0 "${dur}" 0
    fi
}

run_postgres() {
    [[ "${DO_POSTGRES}" != "true" ]] && return 0
    local date_str ts key start dur rc size
    date_str="$(date -u +%Y-%m-%d)"
    ts="$(date -u +%Y-%m-%dT%H-%M-%SZ)"
    key="${date_str}/postgresql-all.${ts}.sql.gz"

    if [[ "${OVERWRITE_SAME_DAY}" != "true" ]] && already_exists_today "${date_str}/postgresql-all."; then
        log "postgresql: today's dump already exists, skipping"
        status_append "postgresql" 0 0 1
        return 0
    fi

    log "postgresql: pg_dumpall via docker exec ${PG_CONTAINER}"
    start=$(now_ms)
    docker exec -i -e "PGPASSWORD=${PG_PASSWORD}" "${PG_CONTAINER}" \
        pg_dumpall -U "${PG_USER}" \
      | gzip -c \
      | aws "${AWS_OPTS[@]}" s3 cp - "s3://${S3_BUCKET}/${key}"
    rc=$?
    dur=$(( $(now_ms) - start ))

    if [[ "${rc}" -eq 0 ]]; then
        size=$(s3_size "${key}")
        log "postgresql: OK (${size} bytes in ${dur}ms) → s3://${S3_BUCKET}/${key}"
        status_append "postgresql" "${size}" "${dur}" 1
    else
        log "postgresql: FAILED (rc=${rc})"
        status_append "postgresql" 0 "${dur}" 0
    fi
}

run_volumes() {
    local date_str ts key start dur rc size vol
    date_str="$(date -u +%Y-%m-%d)"
    for vol in "${VOLUMES[@]}"; do
        [[ -z "${vol}" ]] && continue
        ts="$(date -u +%Y-%m-%dT%H-%M-%SZ)"
        key="${date_str}/volume-${vol}.${ts}.tar.gz"

        if [[ "${OVERWRITE_SAME_DAY}" != "true" ]] && already_exists_today "${date_str}/volume-${vol}."; then
            log "volume/${vol}: today's dump already exists, skipping"
            status_append "volume:${vol}" 0 0 1
            continue
        fi

        log "volume/${vol}: tar-gz via alpine"
        start=$(now_ms)
        docker run --rm -v "${vol}:/data:ro" alpine:3 \
            sh -c 'cd /data && tar -czf - .' \
          | aws "${AWS_OPTS[@]}" s3 cp - "s3://${S3_BUCKET}/${key}"
        rc=$?
        dur=$(( $(now_ms) - start ))

        if [[ "${rc}" -eq 0 ]]; then
            size=$(s3_size "${key}")
            log "volume/${vol}: OK (${size} bytes in ${dur}ms)"
            status_append "volume:${vol}" "${size}" "${dur}" 1
        else
            log "volume/${vol}: FAILED (rc=${rc})"
            status_append "volume:${vol}" 0 "${dur}" 0
        fi
    done
}

run_authentik() {
    [[ "${DO_AUTHENTIK}" != "true" ]] && return 0
    [[ -z "${AUTHENTIK_TOKEN}" ]] && { log "authentik: no token — skipping"; return 0; }

    local date_str ts key start dur rc size tmp
    date_str="$(date -u +%Y-%m-%d)"
    ts="$(date -u +%Y-%m-%dT%H-%M-%SZ)"
    key="${date_str}/authentik-blueprints.${ts}.json.gz"
    tmp="$(mktemp -t nos-authentik.XXXXXX.json)"

    if [[ "${OVERWRITE_SAME_DAY}" != "true" ]] && already_exists_today "${date_str}/authentik-blueprints."; then
        log "authentik: today's dump already exists, skipping"
        status_append "authentik" 0 0 1
        rm -f "${tmp}"
        return 0
    fi

    log "authentik: fetching blueprints from ${AUTHENTIK_URL}"
    start=$(now_ms)
    if curl -fsS -H "Authorization: Bearer ${AUTHENTIK_TOKEN}" \
            -H "Accept: application/json" \
            "${AUTHENTIK_URL}/api/v3/managed/blueprints/" > "${tmp}"; then
        gzip -c "${tmp}" \
          | aws "${AWS_OPTS[@]}" s3 cp - "s3://${S3_BUCKET}/${key}"
        rc=$?
    else
        rc=1
    fi
    dur=$(( $(now_ms) - start ))
    rm -f "${tmp}"

    if [[ "${rc}" -eq 0 ]]; then
        size=$(s3_size "${key}")
        log "authentik: OK (${size} bytes in ${dur}ms)"
        status_append "authentik" "${size}" "${dur}" 1
    else
        log "authentik: FAILED (rc=${rc})"
        status_append "authentik" 0 "${dur}" 0
    fi
}

# ---- Retention / rotation --------------------------------------------------
# Classify all YYYY-MM-DD/ prefixes as:
#   daily   — last N days kept
#   weekly  — the Sunday of each of the last N weeks kept
#   monthly — the 1st of each of the last N months kept
# Everything else is deleted.
rotate() {
    log "rotate: classifying backups (d=${RETAIN_DAILY}, w=${RETAIN_WEEKLY}, m=${RETAIN_MONTHLY})"

    local dates
    dates=$(aws "${AWS_OPTS[@]}" s3 ls "s3://${S3_BUCKET}/" 2>/dev/null \
            | awk '{print $2}' | sed 's|/$||' \
            | grep -E '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' | sort -u)

    if [[ -z "${dates}" ]]; then
        log "rotate: no dated prefixes found, nothing to do"
        return 0
    fi

    local to_delete
    to_delete=$(python3 - <<PY
import datetime as dt
dates = """${dates}""".strip().splitlines()
parsed = sorted({dt.date.fromisoformat(d) for d in dates if d})
today = dt.date.today()
keep = set()

# Daily: last N days
for d in parsed:
    if (today - d).days < ${RETAIN_DAILY}:
        keep.add(d)

# Weekly: Sunday of each of last N weeks (ISO: Monday=1..Sunday=7 → use weekday()==6)
weekly_kept = []
for d in sorted(parsed, reverse=True):
    if d.weekday() == 6 and (today - d).days < ${RETAIN_WEEKLY} * 7 + 7:
        weekly_kept.append(d)
        if len(weekly_kept) >= ${RETAIN_WEEKLY}:
            break
keep.update(weekly_kept)

# Monthly: 1st of each of last N months
monthly_kept = []
for d in sorted(parsed, reverse=True):
    if d.day == 1:
        monthly_kept.append(d)
        if len(monthly_kept) >= ${RETAIN_MONTHLY}:
            break
keep.update(monthly_kept)

delete = [d.isoformat() for d in parsed if d not in keep]
print("\n".join(delete))
PY
)

    if [[ -z "${to_delete}" ]]; then
        log "rotate: nothing to delete"
        return 0
    fi

    local d
    while IFS= read -r d; do
        [[ -z "${d}" ]] && continue
        log "rotate: deleting s3://${S3_BUCKET}/${d}/"
        aws "${AWS_OPTS[@]}" s3 rm "s3://${S3_BUCKET}/${d}/" --recursive \
            >> "${LOG_FILE}" 2>&1 || log "rotate: warning, delete of ${d}/ returned non-zero"
    done <<< "${to_delete}"
}

# ---- Main ------------------------------------------------------------------
main() {
    mkdir -p "$(dirname "${LOG_FILE}")"
    touch "${LOG_FILE}"

    if [[ "${1:-}" == "--rotate-only" ]]; then
        ensure_bucket
        rotate
        exit 0
    fi

    log "==== nOS backup start ===="
    status_reset
    ensure_bucket

    run_mariadb
    run_postgres
    run_volumes
    run_authentik
    rotate

    status_finalize
    log "==== nOS backup done ===="
}

main "$@"
